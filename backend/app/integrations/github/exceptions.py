"""Custom exception hierarchy for the GitHub integration layer.

All GitHub-related errors inherit from ``GitHubError`` so callers can catch
them at whichever level of granularity they need.
"""

from __future__ import annotations


class GitHubError(Exception):
    """Base class for all GitHub integration errors."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class GitHubAuthError(GitHubError):
    """Raised when an API call returns HTTP 401 (invalid/expired token).

    The caller should invalidate any cached installation token and re-mint
    before retrying.
    """

    def __init__(self, message: str = "GitHub authentication failed") -> None:
        super().__init__(message, retryable=True)


class GitHubPermissionDeniedError(GitHubError):
    """Raised when an API call returns HTTP 403.

    The App does not have the required permissions.  Do NOT retry.
    """

    ERROR_CODE = "GITHUB_PERMISSION_DENIED"

    def __init__(self, message: str = "GitHub permission denied") -> None:
        super().__init__(message, retryable=False)


class GitHubNotFoundError(GitHubError):
    """Raised when an API call returns HTTP 404.

    The repository or resource has been deleted or is inaccessible.
    """

    ERROR_CODE = "REPOSITORY_NOT_FOUND"

    def __init__(self, message: str = "GitHub resource not found") -> None:
        super().__init__(message, retryable=False)


class GitHubRateLimitError(GitHubError):
    """Raised when an API call returns HTTP 429 (rate limited).

    ``retry_after_seconds`` is populated from the ``X-RateLimit-Reset`` or
    ``Retry-After`` response header.
    """

    def __init__(self, message: str = "GitHub rate limit exceeded", retry_after_seconds: int = 60) -> None:
        super().__init__(message, retryable=True)
        self.retry_after_seconds = retry_after_seconds


class GitHubInstallationRemovedError(GitHubError):
    """Raised when the App installation has been removed by the user.

    The caller should mark the ``github_installations`` record as inactive.
    """

    def __init__(self, installation_id: int) -> None:
        super().__init__(
            f"GitHub App installation {installation_id} has been removed",
            retryable=False,
        )
        self.installation_id = installation_id


class GitHubCloneError(GitHubError):
    """Raised when ``git clone`` fails for any reason."""

    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message, retryable=False)
        self.returncode = returncode
