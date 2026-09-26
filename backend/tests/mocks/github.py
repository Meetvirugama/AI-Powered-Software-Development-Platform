"""Mock GitHub API endpoints using the `responses` HTTP mock library.

Provides canned responses and configurable mock fixtures for GitHub REST API calls,
including:
- `list_repos` (installation repositories)
- `get_repo` (single repository metadata)
- `installation_token` (app installation access token exchange)
- user profile, user emails, and OAuth access token exchange.
"""

from __future__ import annotations

import re
from typing import Any
import responses

GITHUB_API_BASE = "https://api.github.com"
GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"

DEFAULT_MOCK_USER = {
    "id": 123456,
    "login": "octocat",
    "name": "Monalisa Octocat",
    "email": "octocat@github.com",
    "avatar_url": "https://avatars.githubusercontent.com/u/123456?v=4",
    "html_url": "https://github.com/octocat",
    "type": "User",
}

DEFAULT_MOCK_EMAILS = [
    {
        "email": "octocat@github.com",
        "primary": True,
        "verified": True,
        "visibility": "public",
    }
]

DEFAULT_MOCK_INSTALLATIONS = [
    {
        "id": 98765,
        "account": {
            "login": "octocat",
            "id": 123456,
            "type": "User",
            "avatar_url": "https://avatars.githubusercontent.com/u/123456?v=4",
        },
        "app_id": 11111,
        "target_id": 123456,
        "target_type": "User",
        "permissions": {
            "contents": "read",
            "metadata": "read",
            "pull_requests": "write",
        },
        "events": ["push", "pull_request"],
        "repository_selection": "all",
    }
]

DEFAULT_MOCK_SINGLE_REPO = {
    "id": 55555,
    "name": "sample-repo",
    "full_name": "octocat/sample-repo",
    "owner": {
        "login": "octocat",
        "id": 123456,
    },
    "private": False,
    "html_url": "https://github.com/octocat/sample-repo",
    "clone_url": "https://github.com/octocat/sample-repo.git",
    "default_branch": "main",
    "language": "Python",
}

DEFAULT_MOCK_REPOSITORIES = {
    "total_count": 1,
    "repositories": [DEFAULT_MOCK_SINGLE_REPO],
}


def stub_list_repos(
    rsps: responses.RequestsMock,
    repositories: list[dict[str, Any]] | None = None,
    *,
    status: int = 200,
) -> responses.BaseResponse:
    """Stub response for GitHub list installation repositories API."""
    repos = repositories if repositories is not None else DEFAULT_MOCK_REPOSITORIES["repositories"]
    body = {
        "total_count": len(repos),
        "repositories": repos,
    }
    return rsps.add(
        responses.GET,
        f"{GITHUB_API_BASE}/installation/repositories",
        json=body,
        status=status,
    )


def stub_get_repo(
    rsps: responses.RequestsMock,
    owner: str = "octocat",
    repo: str = "sample-repo",
    repo_data: dict[str, Any] | None = None,
    *,
    status: int = 200,
) -> responses.BaseResponse:
    """Stub response for GitHub get single repository API."""
    data = repo_data if repo_data is not None else DEFAULT_MOCK_SINGLE_REPO
    return rsps.add(
        responses.GET,
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
        json=data,
        status=status,
    )


def stub_installation_token(
    rsps: responses.RequestsMock,
    installation_id: int | str = 98765,
    token: str = "ghs_mock_installation_token_12345",
    *,
    status: int = 201,
) -> responses.BaseResponse:
    """Stub response for GitHub installation access token API."""
    return rsps.add(
        responses.POST,
        f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
        json={
            "token": token,
            "expires_at": "2030-01-01T00:00:00Z",
            "permissions": {"contents": "read", "metadata": "read"},
            "repository_selection": "all",
        },
        status=status,
    )


# Aliases matching alternative task naming conventions
mock_list_repos = stub_list_repos
mock_get_repo = stub_get_repo
mock_installation_token = stub_installation_token


def register_github_mocks(
    rsps: responses.RequestsMock,
    *,
    user: dict[str, Any] | None = None,
    emails: list[dict[str, Any]] | None = None,
    installations: list[dict[str, Any]] | None = None,
    repositories: dict[str, Any] | None = None,
    installation_token: str = "ghs_mock_installation_token_12345",
    oauth_token: str = "gho_mock_oauth_token_67890",
) -> responses.RequestsMock:
    """Register standard GitHub API mock endpoints with a responses.RequestsMock instance."""
    mock_user = user or DEFAULT_MOCK_USER
    mock_emails = emails or DEFAULT_MOCK_EMAILS
    mock_installations = installations or DEFAULT_MOCK_INSTALLATIONS
    repos_list = (repositories or DEFAULT_MOCK_REPOSITORIES)["repositories"]

    # 1. OAuth Access Token Exchange
    rsps.add(
        responses.POST,
        GITHUB_OAUTH_URL,
        json={
            "access_token": oauth_token,
            "token_type": "bearer",
            "scope": "read:user,user:email",
        },
        status=200,
    )

    # 2. Authenticated User Profile
    rsps.add(
        responses.GET,
        f"{GITHUB_API_BASE}/user",
        json=mock_user,
        status=200,
    )

    # 3. User Emails
    rsps.add(
        responses.GET,
        f"{GITHUB_API_BASE}/user/emails",
        json=mock_emails,
        status=200,
    )

    # 4. App Installations
    rsps.add(
        responses.GET,
        f"{GITHUB_API_BASE}/app/installations",
        json=mock_installations,
        status=200,
    )

    # 5. Installation Access Token
    rsps.add(
        responses.POST,
        re.compile(rf"^{GITHUB_API_BASE}/app/installations/\d+/access_tokens$"),
        json={
            "token": installation_token,
            "expires_at": "2030-01-01T00:00:00Z",
            "permissions": {"contents": "read", "metadata": "read"},
            "repository_selection": "all",
        },
        status=201,
    )

    # 6. Installation Repositories (list_repos)
    stub_list_repos(rsps, repos_list)

    # 7. Single Repository (get_repo)
    rsps.add(
        responses.GET,
        re.compile(rf"^{GITHUB_API_BASE}/repos/[^/]+/[^/]+$"),
        json=repos_list[0] if repos_list else DEFAULT_MOCK_SINGLE_REPO,
        status=200,
    )

    return rsps


def create_github_mock() -> responses.RequestsMock:
    """Create and activate a new responses.RequestsMock populated with GitHub defaults."""
    mock = responses.RequestsMock(assert_all_requests_are_fired=False)
    register_github_mocks(mock)
    return mock
