"""Abstract base class for the GitHub integration layer.

All concrete GitHub clients (real API, mocks for testing) must implement
this interface. This keeps the rest of the codebase decoupled from the
actual GitHub API mechanics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Data models returned by the GitHub integration
# ---------------------------------------------------------------------------


@dataclass
class GitHubRepository:
    """Minimal metadata for a GitHub repository."""

    id: int
    owner: str
    name: str
    full_name: str
    description: str | None
    default_branch: str
    language: str | None
    private: bool
    html_url: str
    clone_url: str
    updated_at: datetime | None = None
    size_kb: int = 0


@dataclass
class GitHubBranch:
    """A single branch inside a repository."""

    name: str
    sha: str
    protected: bool = False


@dataclass
class GitHubInstallation:
    """A GitHub App installation record."""

    installation_id: int
    account_login: str
    account_type: str          # "User" or "Organization"
    permissions: dict[str, Any] = field(default_factory=dict)
    installed_at: datetime | None = None


@dataclass
class GitHubIssueData:
    """Metadata for a GitHub issue imported into or created from the platform (Week 3 F31)."""

    number: int
    title: str
    body: str
    state: str
    html_url: str
    labels: list[str] = field(default_factory=list)
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_pull_request: bool = False


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class GitHubIntegrationBase(ABC):
    """Abstract interface for all GitHub API operations used by the platform.

    Subclasses:
    - ``GitHubService`` — real implementation using the GitHub REST API
    - ``MockGitHubService`` — test double (defined in tests/mocks/github.py)
    """

    # ------------------------------------------------------------------
    # Installation / App-level operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_installation(self, installation_id: int) -> GitHubInstallation:
        """Return metadata for a specific App installation."""

    # ------------------------------------------------------------------
    # Repository operations (require installation token)
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_repositories(self, installation_id: int) -> list[GitHubRepository]:
        """List all repositories accessible to this installation."""

    @abstractmethod
    async def get_repository(self, owner: str, repo: str) -> GitHubRepository:
        """Fetch full metadata for a single repository."""

    @abstractmethod
    async def list_branches(self, owner: str, repo: str) -> list[GitHubBranch]:
        """Return all branches for the given repository."""

    @abstractmethod
    async def get_default_branch(self, owner: str, repo: str) -> str:
        """Return the name of the repository's default branch."""

    @abstractmethod
    async def clone_repository(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        branch: str,
        workspace_path: str,
    ) -> str:
        """Shallow-clone a repository into a local workspace directory."""

    # ------------------------------------------------------------------
    # Week 3 F31 — GitHub Issue Integration operations
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
        """Create a GitHub issue on the target repository."""
        raise NotImplementedError

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: int | None = None,
    ) -> GitHubIssueData:
        """Fetch a single GitHub issue by number."""
        raise NotImplementedError

    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        installation_id: int | None = None,
    ) -> list[GitHubIssueData]:
        """List issues for the given repository."""
        raise NotImplementedError
