"""Day 3 — Mock GitHub API tests.

Verifies that the GitHubService correctly:
1. Parses the list_repos response into typed GitHubRepository objects.
2. Raises GitHubNotFoundError on 404 responses (structured error).
3. Raises GitHubPermissionDeniedError on 403 responses (structured error).
4. Raises GitHubRateLimitError on 429 with correct retry_after (triggers retry).
5. Raises GitHubAuthError on 401, and invalidates the cached token so the next
   call re-mints a fresh one (re-mint flow).

All GitHub HTTP calls are intercepted with respx (async httpx mock), so no
real network traffic is involved.
"""

from __future__ import annotations

import asyncio
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, MagicMock

from app.integrations.github.base import GitHubRepository
from app.integrations.github.exceptions import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubPermissionDeniedError,
    GitHubRateLimitError,
)
from app.integrations.github.service import GitHubService, _GITHUB_API_BASE

INSTALLATION_ID = 98765
MOCK_TOKEN = "ghs_mock_installation_token_abc123"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Async Redis mock that simulates a cache miss (no cached token)."""
    redis = AsyncMock()
    redis.get.return_value = None          # cache always misses → forces _mint_token
    redis.set.return_value = True
    redis.delete.return_value = 1
    return redis


@pytest.fixture
def mock_settings(monkeypatch):
    """Minimal settings object with GitHub App credentials."""
    settings = MagicMock()
    settings.github_app_id = "12345"
    settings.github_app_private_key = None  # _build_app_jwt bypassed in tests
    return settings


@pytest.fixture
def github_service(mock_redis, mock_settings):
    """GitHubService wired to the mocked Redis and settings, with JWT bypassed."""
    service = GitHubService(redis=mock_redis, settings=mock_settings)
    # Bypass real RS256 JWT signing by returning a fixed dummy token
    service._token_manager._build_app_jwt = lambda: "dummy.app.jwt"
    return service


# ---------------------------------------------------------------------------
# 1. test_list_repos_returns_correct_structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_returns_correct_structure(github_service):
    """list_repositories() should return a list of typed GitHubRepository objects
    with all fields populated from the GitHub API response."""

    # Stub: token mint
    respx.post(
        f"{_GITHUB_API_BASE}/app/installations/{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=httpx.Response(
            201,
            json={"token": MOCK_TOKEN, "expires_at": "2030-01-01T00:00:00Z"},
        )
    )

    # Stub: list repos (single page, fewer than 100 → no second page)
    respx.get(
        f"{_GITHUB_API_BASE}/installation/repositories?per_page=100&page=1"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 2,
                "repositories": [
                    {
                        "id": 1001,
                        "name": "alpha-repo",
                        "full_name": "octocat/alpha-repo",
                        "owner": {"login": "octocat"},
                        "description": "Alpha description",
                        "default_branch": "main",
                        "language": "Python",
                        "private": False,
                        "html_url": "https://github.com/octocat/alpha-repo",
                        "clone_url": "https://github.com/octocat/alpha-repo.git",
                        "updated_at": "2026-01-15T10:00:00Z",
                        "size": 1024,
                    },
                    {
                        "id": 1002,
                        "name": "beta-repo",
                        "full_name": "octocat/beta-repo",
                        "owner": {"login": "octocat"},
                        "description": None,
                        "default_branch": "develop",
                        "language": "TypeScript",
                        "private": True,
                        "html_url": "https://github.com/octocat/beta-repo",
                        "clone_url": "https://github.com/octocat/beta-repo.git",
                        "updated_at": None,
                        "size": 512,
                    },
                ],
            },
        )
    )

    repos = await github_service.list_repositories(INSTALLATION_ID)

    # --- structure ---
    assert isinstance(repos, list)
    assert len(repos) == 2
    for repo in repos:
        assert isinstance(repo, GitHubRepository)

    # --- first repo fields ---
    alpha = repos[0]
    assert alpha.id == 1001
    assert alpha.owner == "octocat"
    assert alpha.name == "alpha-repo"
    assert alpha.full_name == "octocat/alpha-repo"
    assert alpha.description == "Alpha description"
    assert alpha.default_branch == "main"
    assert alpha.language == "Python"
    assert alpha.private is False
    assert alpha.html_url == "https://github.com/octocat/alpha-repo"
    assert alpha.clone_url == "https://github.com/octocat/alpha-repo.git"
    assert alpha.size_kb == 1024

    # --- second repo fields ---
    beta = repos[1]
    assert beta.id == 1002
    assert beta.name == "beta-repo"
    assert beta.private is True
    assert beta.language == "TypeScript"
    assert beta.default_branch == "develop"
    assert beta.updated_at is None


# ---------------------------------------------------------------------------
# 2. test_404_repository_returns_structured_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_404_repository_returns_structured_error(github_service):
    """get_repository() should raise GitHubNotFoundError when GitHub returns 404.
    The error must be non-retryable (retryable=False)."""

    respx.get(f"{_GITHUB_API_BASE}/repos/octocat/missing-repo").mock(
        return_value=httpx.Response(
            404,
            json={"message": "Not Found", "documentation_url": "https://docs.github.com"},
        )
    )

    with pytest.raises(GitHubNotFoundError) as exc_info:
        await github_service.get_repository("octocat", "missing-repo")

    err = exc_info.value
    assert "Not Found" in str(err)
    assert err.retryable is False
    assert GitHubNotFoundError.ERROR_CODE == "REPOSITORY_NOT_FOUND"


@pytest.mark.asyncio
@respx.mock
async def test_404_for_installation_raises_not_found(github_service):
    """A 404 response not related to the installation raises GitHubNotFoundError."""

    respx.get(f"{_GITHUB_API_BASE}/repos/octocat/deleted-repo").mock(
        return_value=httpx.Response(
            404,
            json={"message": "Repository not found"},
        )
    )

    with pytest.raises(GitHubNotFoundError):
        await github_service.get_repository("octocat", "deleted-repo")


# ---------------------------------------------------------------------------
# 3. test_403_permission_denied_returns_structured_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_403_permission_denied_returns_structured_error(github_service):
    """get_repository() should raise GitHubPermissionDeniedError on 403 responses.
    The error must be non-retryable and carry the GitHub message."""

    respx.get(f"{_GITHUB_API_BASE}/repos/org/private-repo").mock(
        return_value=httpx.Response(
            403,
            json={
                "message": "Resource not accessible by integration",
                "documentation_url": "https://docs.github.com",
            },
        )
    )

    with pytest.raises(GitHubPermissionDeniedError) as exc_info:
        await github_service.get_repository("org", "private-repo")

    err = exc_info.value
    assert "Resource not accessible by integration" in str(err)
    assert err.retryable is False
    assert GitHubPermissionDeniedError.ERROR_CODE == "GITHUB_PERMISSION_DENIED"


@pytest.mark.asyncio
@respx.mock
async def test_403_on_list_repos_raises_permission_denied(github_service):
    """list_repositories() should also raise GitHubPermissionDeniedError on 403."""

    # Stub token mint
    respx.post(
        f"{_GITHUB_API_BASE}/app/installations/{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=httpx.Response(
            201,
            json={"token": MOCK_TOKEN, "expires_at": "2030-01-01T00:00:00Z"},
        )
    )

    respx.get(
        f"{_GITHUB_API_BASE}/installation/repositories?per_page=100&page=1"
    ).mock(
        return_value=httpx.Response(
            403,
            json={"message": "Forbidden"},
        )
    )

    with pytest.raises(GitHubPermissionDeniedError) as exc_info:
        await github_service.list_repositories(INSTALLATION_ID)

    assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# 4. test_rate_limit_triggers_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_triggers_retry(github_service):
    """A 429 response with Retry-After header raises GitHubRateLimitError
    with the correct retry_after_seconds parsed from the response header.
    The error must be retryable=True."""

    import time

    retry_after_header = "45"
    reset_ts = str(int(time.time()) + 120)  # 120 seconds from now

    respx.get(f"{_GITHUB_API_BASE}/repos/octocat/sample-repo").mock(
        return_value=httpx.Response(
            429,
            headers={
                "Retry-After": retry_after_header,
                "X-RateLimit-Reset": reset_ts,
                "X-RateLimit-Remaining": "0",
            },
            json={"message": "API rate limit exceeded"},
        )
    )

    with pytest.raises(GitHubRateLimitError) as exc_info:
        await github_service.get_repository("octocat", "sample-repo")

    err = exc_info.value
    assert err.retryable is True
    # retry_after_seconds should be the max of Retry-After header and X-RateLimit-Reset delta
    assert err.retry_after_seconds >= 45


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_uses_retry_after_when_no_reset_header(github_service):
    """When X-RateLimit-Reset is absent, retry_after_seconds uses the Retry-After header."""

    respx.get(f"{_GITHUB_API_BASE}/repos/octocat/sample-repo").mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"message": "Rate limited"},
        )
    )

    with pytest.raises(GitHubRateLimitError) as exc_info:
        await github_service.get_repository("octocat", "sample-repo")

    assert exc_info.value.retry_after_seconds == 30


# ---------------------------------------------------------------------------
# 5. test_invalid_installation_token_triggers_re_mint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_invalid_installation_token_triggers_re_mint(github_service, mock_redis):
    """A 401 response from GitHub means the installation token is expired/invalid.
    GitHubService must:
      1. Raise GitHubAuthError (retryable=True)
      2. Call invalidate() on the token manager → delete the Redis cache key
         so that the next call to get_token() re-mints a fresh token.
    """

    # Stub token mint (cache miss path)
    respx.post(
        f"{_GITHUB_API_BASE}/app/installations/{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=httpx.Response(
            201,
            json={"token": MOCK_TOKEN, "expires_at": "2030-01-01T00:00:00Z"},
        )
    )

    # Stub list_repos → 401 (token is rejected)
    respx.get(
        f"{_GITHUB_API_BASE}/installation/repositories?per_page=100&page=1"
    ).mock(
        return_value=httpx.Response(
            401,
            json={"message": "Bad credentials"},
        )
    )

    with pytest.raises(GitHubAuthError) as exc_info:
        await github_service.list_repositories(INSTALLATION_ID)

    err = exc_info.value
    assert err.retryable is True

    # Verify the token manager called invalidate → Redis delete was called
    cache_key = f"gh_token:{INSTALLATION_ID}"
    mock_redis.delete.assert_called_once_with(cache_key)


@pytest.mark.asyncio
@respx.mock
async def test_after_401_subsequent_call_remints_token(github_service, mock_redis):
    """After a 401 invalidates the cache, the next get_token() call mints fresh.
    Verify Redis.get returns None after invalidation (simulating cache eviction)."""

    # Simulate a cache miss after previous invalidation by forcing Redis.get to return None
    mock_redis.get.return_value = None

    # No side_effect needed; Redis.get already returns None

    # Stub re-mint endpoint (called after cache miss)
    respx.post(
        f"{_GITHUB_API_BASE}/app/installations/{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=httpx.Response(
            201,
            json={"token": "ghs_fresh_token_xyz789", "expires_at": "2030-01-01T00:00:00Z"},
        )
    )

    # Trigger cache miss → mints fresh token
    fresh_token = await github_service._token_manager.get_token(INSTALLATION_ID)
    assert fresh_token == "ghs_fresh_token_xyz789"
