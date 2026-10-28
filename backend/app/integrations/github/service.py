"""Concrete GitHub API service implementation.

This module provides :class:`GitHubService`, which implements
:class:`~app.integrations.github.base.GitHubIntegrationBase` against the
real GitHub REST API.

Key responsibilities (Parth Week 1–3):
- Week 1 Days 3–5: ``list_repositories``, ``get_repository``, ``list_branches``,
  ``get_default_branch``, ``clone_repository``, error handling.
- Week 3 Day 1 (F31): ``create_issue``, ``get_issue``, ``list_issues`` using
  GitHub App installation tokens and secret redaction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.core.secret_redaction import redact

from .base import (
    GitHubBranch,
    GitHubInstallation,
    GitHubIntegrationBase,
    GitHubIssueData,
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
_SAFE_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GitHubService(GitHubIntegrationBase):
    """GitHub REST API client for the AI-Powered Software Development Platform."""

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

    @staticmethod
    def _validate_owner_and_repo(owner: str, repo: str) -> tuple[str, str]:
        clean_owner = (owner or "").strip()
        clean_repo = (repo or "").strip()
        if not _SAFE_OWNER_REPO_RE.match(clean_owner):
            raise ValueError(f"Invalid repository owner: {owner!r}")
        if not _SAFE_OWNER_REPO_RE.match(clean_repo):
            raise ValueError(f"Invalid repository name: {repo!r}")
        return clean_owner, clean_repo

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

    async def _resolve_headers(self, installation_id: int | None = None) -> dict[str, str]:
        """Return installation auth headers when `installation_id` is supplied, else App JWT headers."""
        if installation_id is not None:
            return await self._installation_auth_headers(int(installation_id))
        return self._app_auth_headers()

    async def _handle_response_errors(
        self,
        response: httpx.Response,
        installation_id: int | None = None,
    ) -> None:
        """Inspect an HTTP response and raise the appropriate exception."""
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
            message = redact(str(body.get("message", "Permission denied")))
            if "installation" in message.lower() and "suspend" in message.lower():
                logger.warning("GitHub App installation suspended: %s", message)
                if installation_id is not None:
                    raise GitHubInstallationRemovedError(installation_id)
            if response.headers.get("X-RateLimit-Remaining") == "0":
                reset_ts = response.headers.get("X-RateLimit-Reset")
                retry_after = 60
                if reset_ts:
                    import time
                    retry_after = max(1, int(reset_ts) - int(time.time()))
                raise GitHubRateLimitError(retry_after_seconds=retry_after)
            raise GitHubPermissionDeniedError(message)

        if status in (404, 410):
            body = response.json() if response.content else {}
            message = redact(str(body.get("message", "Not found")))
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

        response.raise_for_status()

    async def _get(
        self,
        url: str,
        headers: dict[str, str],
        installation_id: int | None = None,
    ) -> Any:
        """Perform a GET request and handle errors uniformly."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        await self._handle_response_errors(response, installation_id)
        return response.json()

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
            number=int(data.get("number", 0)),
            title=redact(str(data.get("title") or "")),
            body=redact(str(data.get("body") or "")),
            state=str(data.get("state") or "open"),
            html_url=str(data.get("html_url") or ""),
            labels=labels,
            author=author,
            created_at=created_at,
            updated_at=updated_at,
            is_pull_request="pull_request" in data,
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
        """List all repositories accessible to this installation."""
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
        """Fetch full metadata for a single repository."""
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

    async def clone_repository(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        branch: str,
        workspace_path: str,
    ) -> str:
        """Shallow-clone a repository using a short-lived installation token."""
        from app.core.input_security import is_within

        target = Path(workspace_path).resolve()
        if not is_within(self._workspace_root, target) or target == self._workspace_root:
            raise ValueError(
                f"workspace_path '{workspace_path}' is outside the allowed "
                f"workspace root '{self._workspace_root}'."
            )

        clean_owner, clean_repo = self._validate_owner_and_repo(owner, repo)
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$", branch or "") or ".." in (branch or ""):
            raise ValueError(f"Invalid branch name: {branch!r}")

        token = await self._token_manager.get_token(installation_id)
        auth_url = f"https://x-access-token:{token}@github.com/{clean_owner}/{clean_repo}.git"

        cmd = [
            "git",
            "clone",
            "--depth=1",
            "--branch",
            branch,
            "--",
            auth_url,
            str(target),
        ]

        logger.info("Cloning %s/%s (branch=%s) into %s", clean_owner, clean_repo, branch, target)

        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=300)

            if result.returncode != 0:
                stderr_text = stderr.decode(errors="replace")
                if token:
                    stderr_text = stderr_text.replace(token, "[REDACTED]")
                logger.error("git clone failed (rc=%d): %s", result.returncode, stderr_text)
                raise GitHubCloneError(
                    f"git clone failed for {clean_owner}/{clean_repo}: {stderr_text}",
                    returncode=result.returncode,
                )
        except (asyncio.TimeoutError, GitHubCloneError):
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                logger.warning("Cleaned up partial clone at %s", target)
            raise

        logger.info("Successfully cloned %s/%s to %s", clean_owner, clean_repo, target)
        return str(target)

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
        """Create a GitHub issue using GitHub App tokens (Parth W3 Day 1 — F31).

        Security (Sukun W3 Day 1):
        - Validates `owner` and `repo` identifiers against path/parameter injection.
        - Redacts secrets from `title`, `body`, and `labels` before outbound GitHub API transmission.
        - Never exposes installation tokens in logs or error messages.
        """
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


# Re-export GitHubSourceService for backwards compatibility with Week 2 source routes
from .source_service import GitHubSourceService  # noqa: E402
