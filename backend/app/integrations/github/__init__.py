"""GitHub integration package owned by Parth.

Provides authorized access to repository files, commit metadata,
branch management, pull-request workflows, and GitHub issues.
"""

from .base import GitHubIntegrationBase
from .client import GitHubAPIError, GitHubClient
from .service import GitHubService
from .source_service import GitHubSourceService
from .token_manager import InstallationTokenManager

__all__ = [
    "GitHubService",
    "GitHubSourceService",
    "GitHubIntegrationBase",
    "InstallationTokenManager",
    "GitHubAPIError",
    "GitHubClient",
]
