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
        """Return metadata for a specific App installation.

        Args:
            installation_id: GitHub's numeric installation ID.

        Returns:
            A :class:`GitHubInstallation` record.

        Raises:
            GitHubNotFoundError: If the installation does not exist.
            GitHubAuthError: If the App JWT is invalid.
        """

    # ------------------------------------------------------------------
    # Repository operations (require installation token)
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_repositories(self, installation_id: int) -> list[GitHubRepository]:
        """List all repositories accessible to this installation.

        Args:
            installation_id: GitHub's numeric installation ID.

        Returns:
            A list of :class:`GitHubRepository` records. May be empty.

        Raises:
            GitHubAuthError: If the installation token cannot be obtained.
            GitHubRateLimitError: If the API rate limit is exceeded.
        """

    @abstractmethod
    async def get_repository(self, owner: str, repo: str) -> GitHubRepository:
        """Fetch full metadata for a single repository.

        Args:
            owner: GitHub user or organization name.
            repo: Repository name.

        Returns:
            A :class:`GitHubRepository` record with full metadata.

        Raises:
            GitHubNotFoundError: If the repository does not exist or is inaccessible.
            GitHubAuthError: If the installation token is invalid.
        """

    @abstractmethod
    async def list_branches(self, owner: str, repo: str) -> list[GitHubBranch]:
        """Return all branches for the given repository.

        Args:
            owner: GitHub user or organization name.
            repo: Repository name.

        Returns:
            Ordered list of :class:`GitHubBranch` records.

        Raises:
            GitHubNotFoundError: If the repository does not exist.
        """

    @abstractmethod
    async def get_default_branch(self, owner: str, repo: str) -> str:
        """Return the name of the repository's default branch.

        Args:
            owner: GitHub user or organization name.
            repo: Repository name.

        Returns:
            Branch name string (e.g. ``"main"`` or ``"master"``).

        Raises:
            GitHubNotFoundError: If the repository does not exist.
        """

    @abstractmethod
    async def clone_repository(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        branch: str,
        workspace_path: str,
    ) -> str:
        """Shallow-clone a repository into a local workspace directory.

        Uses a short-lived installation token so the private key never
        touches disk.  Always performs ``git clone --depth=1``.

        Args:
            installation_id: GitHub App installation ID.
            owner: Repository owner login.
            repo: Repository name.
            branch: Branch to clone.
            workspace_path: Absolute local path where the repo will be cloned.
                            Must be inside the allowed workspace root
                            (no ``../`` path traversal).

        Returns:
            The ``workspace_path`` string on success.

        Raises:
            ValueError: If ``workspace_path`` is outside the allowed root.
            GitHubCloneError: If the clone process fails.
        """
