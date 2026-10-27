"""GitHub integration package owned by Parth.

Provides authorized access to repository files, commit metadata,
branch management, pull-request workflows, and GitHub issues.
"""

from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.service import GitHubService, GitHubSourceService

__all__ = [
    "GitHubAPIError",
    "GitHubClient",
    "GitHubService",
    "GitHubSourceService",
]
