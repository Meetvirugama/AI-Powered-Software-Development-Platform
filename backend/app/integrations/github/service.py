"""Concrete GitHub API service implementation.

This module provides :class:`GitHubService`, which implements
:class:`~app.integrations.github.base.GitHubIntegrationBase` against the
real GitHub REST API.

Key responsibilities (Days 3–5 of Parth's Week 1 plan):
- Day 3: ``list_repositories``, ``get_repository``, ``list_branches``,
         ``get_default_branch`` (repository API wrapper).
- Day 4: ``clone_repository`` (authenticated shallow clone with path validation).
- Day 5: All error codes (401, 403, 404, 429, installation-removed) handled
         gracefully with structured errors and token invalidation.
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
from typing import TYPE_CHECKING

import httpx

from app.core.input_security import is_within
from .base import (
    GitHubBranch,
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
from .token_manager import InstallationTokenManager

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.core.config import Settings

logger = logging.getLogger(__name__)

# Default workspace root. All clones are confined to this directory.
_DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "ai_platform_workspaces"

_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"


class GitHubService(GitHubIntegrationBase):
    """GitHub REST API client for the AI-Powered Software Development Platform.

    Args:
        redis: Async Redis client used by :class:`InstallationTokenManager`.
        settings: Application settings object.
        workspace_root: Base directory where repositories are cloned.
                        Defaults to a platform-specific temp subdirectory.
    """

    def __init__(
        self,
        redis: "Redis",
        settings: "Settings",
        workspace_root: Path | None = None,
    ) -> None:
        self._settings = settings
        self._token_manager = InstallationTokenManager(redis, settings)
        self._workspace_root = (workspace_root or _DEFAULT_WORKSPACE_ROOT).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _app_auth_headers(self) -> dict[str, str]:
        """Return headers for GitHub App-level (JWT) requests."""
        app_jwt = self._token_manager._build_app_jwt()
        return {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }

    async def _installation_auth_headers(self, installation_id: int) -> dict[str, str]:
        """Return headers authenticated as the given installation."""
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
            if installation_id is not None:
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


# Re-export GitHubSourceService for backwards compatibility with Week 2 source routes
from .source_service import GitHubSourceService  # noqa: E402
