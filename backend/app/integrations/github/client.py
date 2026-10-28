"""GitHub API client for authenticated repository operations.

This module provides low-level access to the GitHub REST API using
installation tokens (for GitHub App integrations) or personal access tokens.
It handles authentication, rate limiting, retries, and error mapping.

All methods raise ``GitHubAPIError`` on failure so callers can distinguish
between GitHub errors and application-level errors.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
MAX_FILE_SIZE_BYTES = 1_000_000  # 1 MB — GitHub API limit for contents endpoint
MAX_RETRIES = 2
REQUEST_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GitHubAPIError(Exception):
    """An error returned by the GitHub API or caused by a connectivity failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.rate_limited = rate_limited


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GitHubClient:
    """Thin wrapper around the GitHub REST API.

    Parameters
    ----------
    token : str
        A GitHub access token (installation token or PAT).
    base_url : str, optional
        Override for GitHub Enterprise Server instances.
    """

    def __init__(self, token: str, *, base_url: str = GITHUB_API_BASE) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ----- internal helpers ------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str | None = None,
        raw: bool = False,
    ) -> Any:
        """Execute an authenticated GitHub API request with bounded retries."""
        url = f"{self._base_url}{path}"
        headers = dict(self._headers)
        if accept:
            headers["Accept"] = accept

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    )

                if response.status_code == 403:
                    remaining = response.headers.get("x-ratelimit-remaining", "")
                    if remaining == "0":
                        raise GitHubAPIError(
                            "GitHub API rate limit exceeded.",
                            status_code=403,
                            retryable=True,
                            rate_limited=True,
                        )

                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after", "")
                    reset_time = response.headers.get("x-ratelimit-reset", "")
                    raise GitHubAPIError(
                        f"GitHub API rate limit exceeded (HTTP 429). Retry-After: {retry_after or reset_time}s.",
                        status_code=429,
                        retryable=True,
                        rate_limited=True,
                    )

                if response.status_code == 404:
                    raise GitHubAPIError(
                        f"Resource not found: {path}",
                        status_code=404,
                    )

                if response.status_code >= 500:
                    raise GitHubAPIError(
                        f"GitHub server error ({response.status_code}).",
                        status_code=response.status_code,
                        retryable=True,
                    )

                response.raise_for_status()

                if raw:
                    return response.text

                return response.json()

            except GitHubAPIError:
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                raise GitHubAPIError(
                    f"GitHub API error ({exc.response.status_code}): {exc.response.text[:200]}",
                    status_code=exc.response.status_code,
                    retryable=exc.response.status_code >= 500,
                ) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "GitHub API request failed (attempt %d/%d): %s",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        str(exc),
                    )
                    continue
                raise GitHubAPIError(
                    f"GitHub API is unavailable: {exc}",
                    retryable=True,
                ) from exc

        # Should not be reached, but be defensive
        raise GitHubAPIError(
            f"GitHub API request failed after {MAX_RETRIES + 1} attempts.",
            retryable=True,
        ) from last_exc

    # ----- Repository content ----------------------------------------------

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve a single file from a repository via the contents API.

        Returns the raw GitHub API response including ``content``, ``encoding``,
        ``sha``, and ``size``.
        """
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref
        return await self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    async def get_file_tree(
        self,
        owner: str,
        repo: str,
        *,
        ref: str | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Retrieve the full tree for a repository.

        Uses ``GET /repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1``
        for a flat listing of all paths.
        """
        tree_sha = ref or "HEAD"
        params: dict[str, str] = {}
        if recursive:
            params["recursive"] = "1"
        return await self._request("GET", f"/repos/{owner}/{repo}/git/trees/{tree_sha}", params=params)

    # ----- Commits ---------------------------------------------------------

    async def list_commits(
        self,
        owner: str,
        repo: str,
        *,
        sha: str | None = None,
        path: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List commits for a repository with optional filters."""
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        return await self._request("GET", f"/repos/{owner}/{repo}/commits", params=params)

    async def get_commit(
        self,
        owner: str,
        repo: str,
        sha: str,
    ) -> dict[str, Any]:
        """Get detailed information about a single commit including file changes."""
        return await self._request("GET", f"/repos/{owner}/{repo}/commits/{sha}")

    # ----- Pull requests ---------------------------------------------------

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        per_page: int = 30,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List pull requests for a repository."""
        params: dict[str, Any] = {
            "state": state,
            "per_page": per_page,
            "page": page,
        }
        return await self._request("GET", f"/repos/{owner}/{repo}/pulls", params=params)

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> dict[str, Any]:
        """Get metadata for a single pull request."""
        return await self._request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")

    async def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Get the list of files changed in a pull request."""
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            params=params,
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
    ) -> dict[str, Any]:
        """Create a pull request on GitHub (defaults to Draft PR)."""
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        }
        return await self._request("POST", f"/repos/{owner}/{repo}/pulls", json_body=payload)

    async def update_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str | None = None,
        title: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing pull request on GitHub."""
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if title is not None:
            payload["title"] = title
        if state is not None:
            payload["state"] = state
        return await self._request("PATCH", f"/repos/{owner}/{repo}/pulls/{pr_number}", json_body=payload)

    # ----- Issues (F-23) ---------------------------------------------------

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new issue on GitHub (e.g. from AI code review finding F-23)."""
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return await self._request("POST", f"/repos/{owner}/{repo}/issues", json_body=payload)

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Retrieve issue details by issue number."""
        return await self._request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    # ----- Git References and Branches ------------------------------------

    async def get_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> dict[str, Any]:
        """Get branch information including latest commit SHA."""
        return await self._request("GET", f"/repos/{owner}/{repo}/branches/{branch}")

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        source_sha: str,
    ) -> dict[str, Any]:
        """Create a new Git branch pointing to source_sha.

        Creates git ref 'refs/heads/{branch_name}'.
        """
        ref_path = f"refs/heads/{branch_name.lstrip('/')}"
        payload = {"ref": ref_path, "sha": source_sha}
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json_body=payload,
        )

    async def delete_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> None:
        """Delete a Git branch by deleting its ref.

        Deletes git ref 'refs/heads/{branch_name}'.
        """
        clean_name = branch_name.removeprefix("refs/heads/")
        await self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/git/refs/heads/{clean_name}",
        )

    async def get_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
    ) -> dict[str, Any]:
        """Get a Git ref by path (e.g. 'heads/main' or 'heads/agent/task-123')."""
        clean_ref = ref.removeprefix("refs/")
        return await self._request("GET", f"/repos/{owner}/{repo}/git/ref/{clean_ref}")

    # ----- Installation token management -----------------------------------

    @staticmethod
    async def get_installation_token(installation_id: str) -> str:
        """Exchange a GitHub App JWT for an installation access token.

        This requires ``GITHUB_APP_ID`` and ``GITHUB_APP_PRIVATE_KEY`` to be
        configured. Returns the short-lived installation token.
        """
        settings = get_settings()
        if not settings.github_app_id or not settings.github_app_private_key:
            raise GitHubAPIError(
                "GitHub App credentials are not configured.",
                status_code=500,
            )

        import time
        from jose import jwt as jose_jwt

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": settings.github_app_id,
        }
        app_jwt = jose_jwt.encode(
            payload,
            settings.github_app_private_key,
            algorithm="RS256",
        )

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if response.status_code != 201:
                raise GitHubAPIError(
                    f"Failed to obtain installation token: {response.text[:200]}",
                    status_code=response.status_code,
                    retryable=response.status_code >= 500,
                )
            data = response.json()

        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise GitHubAPIError(
                "GitHub returned an invalid installation token.",
                status_code=502,
                retryable=True,
            )
        return token
