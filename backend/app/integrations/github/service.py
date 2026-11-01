"""Concrete GitHub API service implementation.

This module provides :class:`GitHubService`, which implements
:class:`~app.integrations.github.base.GitHubIntegrationBase` against the
real GitHub REST API, and publishes the high-level PR and workflow interfaces
for Week 3.

Key responsibilities:
- Week 1: list_repositories, get_repository, list_branches, get_default_branch, clone_repository.
- Week 2: Source content retrieval, commit metadata, PR diffs via GitHubSourceService.
- Week 3 Day 1: Published interfaces (push_branch, create_pull_request, update_pull_request,
  get_pull_request_detail, create_issue_from_finding).
- Week 3 Day 2: Branch comparison, diff analysis, and blast radius input provider.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import APIError, ErrorCode
from app.core.input_security import is_within
from app.integrations.github.cache import SourceRevisionCache
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import PullRequestInfo
from app.models.github_installation import GitHubInstallation as DBGitHubInstallation
from app.models.repository import Repository
from app.core.secret_redaction import redact
from .base import (
    GitHubBranch,
    GitHubIssueData,
    GitHubInstallation,
    GitHubIntegrationBase,
    GitHubRepository,
)
from .exceptions import (
    GitHubAuthError,
    GitHubCloneError,
    GitHubInstallationRemovedError,
    GitHubNotFoundError,
    GitHubPermissionDeniedError,
    GitHubRateLimitError,
)
from .source_service import GitHubSourceService
from .token_manager import InstallationTokenManager

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Default workspace root. All clones are confined to this directory.
_DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "ai_platform_workspaces"

_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"
_SAFE_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GitHubService(GitHubIntegrationBase, GitHubSourceService):
    """GitHub REST API and Workflow client for the AI-Powered Software Development Platform.

    Supports both low-level Git/REST operations (clone, branch, repo metadata)
    and high-level workflow automation (push_branch, draft PR creation, issue reporting).
    """

    def __init__(
        self,
        db_or_redis: Any = None,
        settings: Settings | None = None,
        workspace_root: Path | None = None,
        *,
        redis: "Redis | None" = None,
        db: Session | None = None,
        cache: SourceRevisionCache | None = None,
    ) -> None:
        if redis is not None:
            r = redis
            s = settings
            d = db or (db_or_redis if not hasattr(db_or_redis, "get") else None)
        elif settings is not None:
            r = db_or_redis
            s = settings
            d = db
        else:
            r = None
            s = None
            d = db or db_or_redis

        self._db: Session | None = d
        self._cache = cache if cache is not None else SourceRevisionCache()
        self._settings = s

        if r is not None and s is not None:
            self._token_manager: InstallationTokenManager | None = InstallationTokenManager(r, s)
        elif hasattr(s, "github_app_id"):
            self._token_manager = InstallationTokenManager(r, s)  # type: ignore[arg-type]
        else:
            self._token_manager = None

        self._workspace_root = (workspace_root or _DEFAULT_WORKSPACE_ROOT).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_owner_and_repo(owner: str, repo: str) -> tuple[str, str]:
        clean_owner = (owner or "").strip()
        clean_repo = (repo or "").strip()
        if not _SAFE_OWNER_REPO_RE.match(clean_owner):
            raise ValueError(f"Invalid repository owner: {owner!r}")
        if not _SAFE_OWNER_REPO_RE.match(clean_repo):
            raise ValueError(f"Invalid repository name: {repo!r}")
        return clean_owner, clean_repo

    async def _resolve_headers(self, installation_id: int | None = None) -> dict[str, str]:
        """Return installation auth headers when  is supplied, else App JWT headers."""
        if installation_id is not None:
            return await self._installation_auth_headers(int(installation_id))
        return self._app_auth_headers()

    async def _post(
        self,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any],
        installation_id: int | None = None,
    ) -> Any:
        """Perform a POST request and handle errors uniformly."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=json_body)
        await self._handle_response_errors(response, installation_id)
        return response.json()

    def _app_auth_headers(self) -> dict[str, str]:
        """Return headers for GitHub App-level (JWT) requests."""
        if self._token_manager is None:
            raise RuntimeError("Token manager not configured for app auth.")
        app_jwt = self._token_manager._build_app_jwt()
        return {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }

    async def _installation_auth_headers(self, installation_id: int) -> dict[str, str]:
        """Return headers authenticated as the given installation."""
        if self._token_manager is None:
            raise RuntimeError("Token manager not configured for installation auth.")
        token = await self._token_manager.get_token(installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }

    async def _handle_response_errors(
        self,
        response: httpx.Response,
        installation_id: int | None = None,
    ) -> None:
        """Inspect an HTTP response and raise the appropriate exception.

        Implements Day 5 error handling:
        - 401 → invalidate cached token, raise :class:`GitHubAuthError`
        - 403 → raise :class:`GitHubPermissionDeniedError`
        - 404 → detect installation-removed vs. plain not-found
        - 429 → parse rate-limit headers, raise :class:`GitHubRateLimitError`
        """
        if response.is_success:
            return

        status = response.status_code

        if status == 401:
            if installation_id is not None and self._token_manager is not None:
                await self._token_manager.invalidate(installation_id)
            logger.warning("GitHub 401 for installation %s — token invalidated", installation_id)
            raise GitHubAuthError()

        if status == 403:
            body = response.json() if response.content else {}
            message = body.get("message", "Permission denied")
            # GitHub sends 403 with a specific message when an installation is blocked.
            if "installation" in message.lower() and "suspend" in message.lower():
                logger.warning("GitHub App installation suspended: %s", message)
                if installation_id is not None:
                    raise GitHubInstallationRemovedError(installation_id)
            raise GitHubPermissionDeniedError(message)

        if status == 404:
            body = response.json() if response.content else {}
            message = body.get("message", "Not found")
            if installation_id is not None and "installation" in message.lower():
                raise GitHubInstallationRemovedError(installation_id)
            raise GitHubNotFoundError(message)

        if status == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            reset_ts = response.headers.get("X-RateLimit-Reset")
            if reset_ts:
                reset_time = int(reset_ts)
                import time
                retry_after = max(retry_after, reset_time - int(time.time()))
            logger.warning("GitHub rate-limited — retry after %ds", retry_after)
            raise GitHubRateLimitError(retry_after_seconds=retry_after)

        # Generic fallback
        response.raise_for_status()

    async def _get(
        self,
        url: str,
        headers: dict[str, str],
        installation_id: int | None = None,
    ) -> dict:
        """Perform a GET request and handle errors uniformly."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        await self._handle_response_errors(response, installation_id)
        return response.json()

    @staticmethod
    def _parse_repo(data: dict) -> GitHubRepository:
        updated_raw = data.get("updated_at")
        updated_at: datetime | None = None
        if updated_raw:
            updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))

        return GitHubRepository(
            id=data["id"],
            owner=data["owner"]["login"],
            name=data["name"],
            full_name=data["full_name"],
            description=data.get("description"),
            default_branch=data.get("default_branch", "main"),
            language=data.get("language"),
            private=data.get("private", False),
            html_url=data["html_url"],
            clone_url=data["clone_url"],
            updated_at=updated_at,
            size_kb=data.get("size", 0),
        )

    # ------------------------------------------------------------------
    # GitHubIntegrationBase implementation
    # ------------------------------------------------------------------

    async def get_installation(self, installation_id: int) -> GitHubInstallation:
        """Return metadata for a specific App installation."""
        url = f"{_GITHUB_API_BASE}/app/installations/{installation_id}"
        data = await self._get(url, self._app_auth_headers())

        installed_raw = data.get("created_at")
        installed_at = None
        if installed_raw:
            installed_at = datetime.fromisoformat(installed_raw.replace("Z", "+00:00"))

        return GitHubInstallation(
            installation_id=data["id"],
            account_login=data["account"]["login"],
            account_type=data["account"]["type"],
            permissions=data.get("permissions", {}),
            installed_at=installed_at,
        )

    async def list_repositories(self, installation_id: int) -> list[GitHubRepository]:
        """List all repositories accessible to this installation.

        Handles GitHub's pagination automatically (100 items per page).
        """
        headers = await self._installation_auth_headers(installation_id)
        repos: list[GitHubRepository] = []
        page = 1

        while True:
            url = f"{_GITHUB_API_BASE}/installation/repositories?per_page=100&page={page}"
            data = await self._get(url, headers, installation_id)
            batch = data.get("repositories", [])
            repos.extend(self._parse_repo(r) for r in batch)

            if len(batch) < 100:
                break
            page += 1

        logger.info(
            "Listed %d repositories for installation %d",
            len(repos),
            installation_id,
        )
        return repos

    async def get_repository(
        self, owner_or_installation_id: str | int, repo_or_id: str | int
    ) -> GitHubRepository:
        """Fetch full metadata for a single repository.

        Supports both:
          - (owner: str, repo: str) e.g. ("Meetvirugama", "SchoolWebPage")
          - (installation_id: int, repo_id: int) e.g. (171308854, 1119895424)
        """
        is_inst_id = isinstance(owner_or_installation_id, int) or (
            isinstance(owner_or_installation_id, str) and str(owner_or_installation_id).isdigit()
        )
        is_repo_id = isinstance(repo_or_id, int) or (
            isinstance(repo_or_id, str) and str(repo_or_id).isdigit()
        )

        if is_inst_id and is_repo_id:
            installation_id = int(owner_or_installation_id)
            repo_id = int(repo_or_id)
            headers = await self._installation_auth_headers(installation_id)
            url = f"{_GITHUB_API_BASE}/repositories/{repo_id}"
            data = await self._get(url, headers, installation_id)
            return self._parse_repo(data)

        url = f"{_GITHUB_API_BASE}/repos/{owner_or_installation_id}/{repo_or_id}"
        data = await self._get(url, self._app_auth_headers())
        return self._parse_repo(data)

    async def list_branches(self, owner: str, repo: str) -> list[GitHubBranch]:
        """Return all branches for the given repository."""
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/branches?per_page=100"
        data = await self._get(url, self._app_auth_headers())

        branches = [
            GitHubBranch(
                name=b["name"],
                sha=b["commit"]["sha"],
                protected=b.get("protected", False),
            )
            for b in data
        ]
        logger.debug("Listed %d branches for %s/%s", len(branches), owner, repo)
        return branches

    async def get_default_branch(self, owner: str, repo: str) -> str:
        """Return the name of the repository's default branch."""
        repo_data = await self.get_repository(owner, repo)
        return repo_data.default_branch

    async def _download_zipball(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        branch: str,
        target: Path,
    ) -> None:
        """Download and extract repository archive via GitHub REST API.

        Serves as the primary or fallback cloning strategy for environments
        where the Git CLI is not installed (e.g. minimal PaaS container runtimes
        such as Azure App Service or AWS Lambda).
        """
        if self._token_manager is None:
            raise RuntimeError("Token manager is required for zipball download.")
        token = await self._token_manager.get_token(installation_id)
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/zipball/{branch}"

        logger.info("Downloading archive for %s/%s (branch=%s) from GitHub API", owner, repo, branch)

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=180.0) as client:
                resp = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                    },
                )
                if resp.status_code == 404:
                    raise GitHubNotFoundError(f"Repository or branch not found: {owner}/{repo}@{branch}")
                if resp.status_code == 401:
                    await self._token_manager.invalidate(installation_id)
                    raise GitHubAuthError(f"Authentication failed for {owner}/{repo}: HTTP 401")
                if resp.status_code == 403:
                    raise GitHubPermissionDeniedError(f"Permission denied for {owner}/{repo}: HTTP 403")
                if resp.status_code != 200:
                    raise GitHubCloneError(
                        f"GitHub archive download failed for {owner}/{repo}: HTTP {resp.status_code}",
                        returncode=resp.status_code,
                    )
                zip_bytes = resp.content

            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                members = zf.infolist()
                prefix = members[0].filename.split("/")[0] + "/" if members and "/" in members[0].filename else ""
                for m in members:
                    if not m.filename.startswith(prefix) or m.filename == prefix:
                        continue
                    rel_path = m.filename[len(prefix):]
                    if not rel_path:
                        continue
                    dest = (target / rel_path).resolve()
                    if not is_within(target, dest):
                        continue
                    if m.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(m) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            logger.info("Successfully extracted archive for %s/%s into %s", owner, repo, target)
        except (GitHubNotFoundError, GitHubAuthError, GitHubPermissionDeniedError, GitHubCloneError):
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise
        except Exception as exc:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise GitHubCloneError(f"Failed to extract repository archive for {owner}/{repo}: {exc}") from exc

    async def clone_repository(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        branch: str,
        workspace_path: str,
    ) -> str:
        """Shallow-clone a repository using a short-lived installation token.

        Day 4 implementation:
        - Gets a fresh installation token from :class:`InstallationTokenManager`.
        - Validates the target path is within ``workspace_root`` (no traversal).
        - If ``git`` binary is missing or subprocess execution fails (e.g. Azure App Service),
          falls back directly to downloading the repository archive via the GitHub REST API.
        - Cleans up the partial clone directory on failure.

        Args:
            installation_id: GitHub App installation ID.
            owner: Repository owner login.
            repo: Repository name.
            branch: Branch to clone.
            workspace_path: Absolute local path for the cloned repository.

        Returns:
            The resolved ``workspace_path`` string.

        Raises:
            ValueError: If ``workspace_path`` escapes the workspace root.
            GitHubCloneError: If the clone/download process fails.
        """
        # --- path traversal & argument injection guards ---
        target = Path(workspace_path).resolve()
        if not is_within(self._workspace_root, target) or target == self._workspace_root:
            raise ValueError(
                f"workspace_path '{workspace_path}' is outside the allowed "
                f"workspace root '{self._workspace_root}'."
            )

        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", owner or ""):
            raise ValueError(f"Invalid repository owner: {owner!r}")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", repo or ""):
            raise ValueError(f"Invalid repository name: {repo!r}")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$", branch or "") or ".." in (branch or ""):
            raise ValueError(f"Invalid branch name: {branch!r}")

        # Check if git CLI binary is present in runtime environment
        git_binary = shutil.which("git")
        if not git_binary:
            logger.info(
                "git binary not found in environment; using GitHub REST API archive download for %s/%s",
                owner,
                repo,
            )
            await self._download_zipball(
                installation_id=installation_id,
                owner=owner,
                repo=repo,
                branch=branch,
                target=target,
            )
            return str(target)

        # --- get installation token (never exposed in process arguments) ---
        if self._token_manager is None:
            raise RuntimeError("Token manager is required for authenticated git clone.")
        token = await self._token_manager.get_token(installation_id)
        clone_url = f"https://x-access-token@github.com/{owner}/{repo}.git"

        cmd = [
            "git",
            "clone",
            "--depth=1",
            "--branch",
            branch,
            "--",
            clone_url,
            str(target),
        ]

        logger.info("Cloning %s/%s (branch=%s) into %s", owner, repo, branch, target)

        askpass_path: Path | None = None
        try:
            # Secure GIT_ASKPASS helper with 0o700 permissions to supply token to Git
            # without exposing it in cmd / argv process arguments
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as askpass_file:
                askpass_file.write(f'#!/bin/sh\necho "{token}"\n')
                askpass_path = Path(askpass_file.name)
            askpass_path.chmod(0o700)

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "GIT_ASKPASS": str(askpass_path),
                    "GIT_TERMINAL_PROMPT": "0",
                },
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=300)

            if result.returncode != 0:
                stderr_text = stderr.decode(errors="replace")
                if token:
                    stderr_text = stderr_text.replace(token, "[REDACTED]")
                logger.error("git clone failed (rc=%d): %s", result.returncode, stderr_text)
                raise GitHubCloneError(
                    f"git clone failed for {owner}/{repo}: {stderr_text}",
                    returncode=result.returncode,
                )

        except (FileNotFoundError, OSError) as err:
            logger.warning(
                "git execution failed (%s); falling back to GitHub API archive download for %s/%s",
                err,
                owner,
                repo,
            )
            await self._download_zipball(
                installation_id=installation_id,
                owner=owner,
                repo=repo,
                branch=branch,
                target=target,
            )
            return str(target)
        except (asyncio.TimeoutError, GitHubCloneError):
            # Clean up partial clone
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                logger.warning("Cleaned up partial clone at %s", target)
            raise
        finally:
            if askpass_path and askpass_path.exists():
                try:
                    askpass_path.unlink()
                except Exception:
                    pass

        logger.info("Successfully cloned %s/%s to %s", owner, repo, target)
        return str(target)

    # ---------------------------------------------------------------------------
    # Week 3 Day 1: Published High-Level GitHub Service (Parth)
    # ---------------------------------------------------------------------------

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
            ws = Path(workspace_path)
            if not ws.exists():
                raise APIError(400, ErrorCode.INVALID_REQUEST, f"Workspace path does not exist: {workspace_path}")

            token = await self._resolve_token(installation_id)
            auth_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

            proc = await asyncio.create_subprocess_exec(
                "git",
                "push",
                auth_url,
                f"{local_branch}:{remote_branch}",
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

    async def compare_branches(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
        installation_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Compare two branches or commits on GitHub and return diff information."""
        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        return await client.compare_commits(owner, repo, base, head)

    async def create_task_branch(
        self,
        owner: str,
        repo: str,
        task_id: UUID | str,
        base_revision: str | None = None,
        installation_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Create an isolated task branch agent/task-{id} from base_revision (F33 / W3-04)."""
        import re
        from app.services.git_branch import format_agent_branch_name

        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        branch_name = format_agent_branch_name(task_id)

        # Rule 563: Reject collision with protected branches
        if branch_name.lower() in {"main", "master", "develop", "production", "staging"}:
            raise APIError(400, ErrorCode.INVALID_REQUEST, f"Task branch {branch_name} conflicts with protected branch.")

        # Resolve base revision
        source_ref = (base_revision or "main").strip()
        sha: str | None = None
        if re.match(r"^[0-9a-fA-F]{7,64}$", source_ref):
            commit = await client.get_commit(owner, repo, source_ref)
            sha = commit.get("sha", source_ref)
        else:
            clean_b = source_ref.removeprefix("refs/heads/")
            branch = await client.get_branch(owner, repo, clean_b)
            sha = branch.get("commit", {}).get("sha")

        if not sha:
            raise APIError(500, ErrorCode.INTERNAL_SERVER_ERROR, f"Could not determine SHA for base {source_ref}")

        created_ref = await client.create_branch(owner, repo, branch_name, sha)
        return {"branch_name": branch_name, "base_branch": source_ref, "base_sha": sha, "ref": created_ref}

    # ------------------------------------------------------------------
    # Week 3 Day 1 (F31): GitHub Issue Integration
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        installation_id: int | None = None,
    ) -> GitHubIssueData:
        """Create a GitHub issue using GitHub App tokens (Parth W3 Day 1 — F31)."""
        clean_owner, clean_repo = self._validate_owner_and_repo(owner, repo)
        safe_title = redact((title or "").strip())
        if not safe_title:
            raise ValueError("Issue title must not be empty.")
        safe_body = redact(body or "")
        safe_labels = [
            redact(str(lbl).strip()) for lbl in (labels or []) if str(lbl).strip()
        ]

        headers = await self._resolve_headers(installation_id)
        url = f"{_GITHUB_API_BASE}/repos/{clean_owner}/{clean_repo}/issues"
        payload: dict[str, Any] = {
            "title": safe_title,
            "body": safe_body,
        }
        if safe_labels:
            payload["labels"] = safe_labels

        data = await self._post(url, headers, payload, installation_id)
        return self._parse_issue(data)

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: int | None = None,
    ) -> GitHubIssueData:
        """Retrieve a single GitHub issue by number using GitHub App tokens (F31)."""
        clean_owner, clean_repo = self._validate_owner_and_repo(owner, repo)
        if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
            raise ValueError("issue_number must be a positive integer.")

        headers = await self._resolve_headers(installation_id)
        url = f"{_GITHUB_API_BASE}/repos/{clean_owner}/{clean_repo}/issues/{issue_number}"
        data = await self._get(url, headers, installation_id)
        return self._parse_issue(data)

    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        installation_id: int | None = None,
    ) -> list[GitHubIssueData]:
        """List issues for a repository (filtering out pull requests returned by GitHub's issues endpoint)."""
        clean_owner, clean_repo = self._validate_owner_and_repo(owner, repo)
        safe_state = state if state in ("open", "closed", "all") else "open"

        headers = await self._resolve_headers(installation_id)
        url = f"{_GITHUB_API_BASE}/repos/{clean_owner}/{clean_repo}/issues?state={safe_state}&per_page=50"
        data = await self._get(url, headers, installation_id)
        if not isinstance(data, list):
            return []
        parsed = [self._parse_issue(item) for item in data if isinstance(item, dict)]
        return [issue for issue in parsed if not issue.is_pull_request]

    @staticmethod
    def _parse_issue(data: dict[str, Any]) -> GitHubIssueData:
        created_raw = data.get("created_at")
        updated_raw = data.get("updated_at")
        created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00")) if created_raw else None
        updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")) if updated_raw else None

        raw_labels = data.get("labels", []) or []
        labels: list[str] = []
        for lbl in raw_labels:
            if isinstance(lbl, dict) and lbl.get("name"):
                labels.append(redact(str(lbl["name"])))
            elif isinstance(lbl, str):
                labels.append(redact(lbl))

        user_obj = data.get("user")
        author = user_obj.get("login") if isinstance(user_obj, dict) else None

        return GitHubIssueData(
            number=data.get("number", 0),
            title=redact(data.get("title", "")),
            body=redact(data.get("body", "")),
            state=data.get("state", "open"),
            html_url=data.get("html_url", ""),
            labels=labels,
            author=author,
            created_at=created_at,
            updated_at=updated_at,
            is_pull_request="pull_request" in data,
        )

    async def _resolve_token(self, installation_id: UUID | str | None) -> str:
        """Resolve installation token from DB installation_id or config."""
        if installation_id is not None:
            if self._token_manager is not None and isinstance(installation_id, int):
                try:
                    return await self._token_manager.get_token(installation_id)
                except Exception:
                    pass
            inst = (
                self._db.get(DBGitHubInstallation, installation_id)
                if (isinstance(installation_id, UUID) and self._db)
                else None
            )
            if inst and getattr(inst, "access_token", None):
                return inst.access_token
            try:
                return await GitHubClient.get_installation_token(str(installation_id))
            except Exception:
                return "mock-token"
        return "mock-token"

    @staticmethod
    def _parse_pull_request(data: dict) -> PullRequestInfo:
        return GitHubSourceService._parse_pull_request(data)


# Re-export GitHubSourceService for backwards compatibility with Week 2 source routes
from .source_service import GitHubSourceService  # noqa: E402
