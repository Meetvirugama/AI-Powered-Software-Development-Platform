"""Redis-backed installation token manager for the GitHub App.

GitHub App installation tokens expire after **1 hour**.  This manager
caches valid tokens in Redis (TTL = 55 minutes) so that most token
look-ups are a simple cache read rather than a GitHub API round-trip.

Usage::

    manager = InstallationTokenManager(redis_client, settings)
    token = await manager.get_token(installation_id=12345678)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx
import jwt  # PyJWT

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.core.config import Settings

logger = logging.getLogger(__name__)

# How long (in seconds) to keep a token cached.  GitHub tokens last 60
# minutes; we refresh 5 minutes early to avoid edge-case expirations.
_TOKEN_CACHE_TTL_SECONDS = 55 * 60  # 55 minutes

# Redis key template for cached tokens.
_CACHE_KEY = "gh_token:{installation_id}"

# GitHub App JWT lives for 10 minutes (GitHub maximum is 10 minutes).
_APP_JWT_EXPIRY_SECONDS = 600


class InstallationTokenManager:
    """Manages short-lived GitHub App installation access tokens.

    The manager handles:
    - Generating a signed GitHub App JWT from the App private key.
    - Exchanging the JWT for an installation token via GitHub's REST API.
    - Caching the token in Redis to minimize API calls.
    - Thread-safe token renewal on cache misses.

    Args:
        redis: An async Redis client instance.
        settings: Application settings (provides ``GITHUB_APP_ID`` and
                  ``GITHUB_APP_PRIVATE_KEY``).
    """

    def __init__(self, redis: "Redis", settings: "Settings") -> None:  # noqa: UP037
        self._redis = redis
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_token(self, installation_id: int) -> str:
        """Return a valid installation access token.

        Checks Redis first.  If the cached token is missing or close to
        expiry, mints a fresh token and caches it.

        Args:
            installation_id: GitHub's numeric installation ID.

        Returns:
            A short-lived installation access token string.

        Raises:
            ValueError: If GitHub App credentials are not configured.
            httpx.HTTPStatusError: If the GitHub API returns a non-2xx response.
        """
        cache_key = _CACHE_KEY.format(installation_id=installation_id)

        # --- cache hit ---
        cached = await self._redis.get(cache_key)
        if cached:
            logger.debug("GitHub token cache HIT for installation %d", installation_id)
            return cached.decode() if isinstance(cached, bytes) else cached

        # --- cache miss: mint a new token ---
        logger.info("GitHub token cache MISS for installation %d — minting new token", installation_id)
        token = await self._mint_token(installation_id)

        await self._redis.set(cache_key, token, ex=_TOKEN_CACHE_TTL_SECONDS)
        logger.debug("Cached GitHub token for installation %d (TTL=%ds)", installation_id, _TOKEN_CACHE_TTL_SECONDS)

        return token

    async def invalidate(self, installation_id: int) -> None:
        """Remove a cached token, forcing re-mint on the next call.

        Call this when a 401 response is received from the GitHub API.

        Args:
            installation_id: GitHub's numeric installation ID.
        """
        cache_key = _CACHE_KEY.format(installation_id=installation_id)
        await self._redis.delete(cache_key)
        logger.info("Invalidated cached GitHub token for installation %d", installation_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_app_jwt(self) -> str:
        """Sign and return a short-lived GitHub App JWT.

        The JWT is used to authenticate as the GitHub App itself (not as
        a specific installation).  It is only valid for 10 minutes.

        Returns:
            A signed JWT string.

        Raises:
            ValueError: If ``GITHUB_APP_ID`` or ``GITHUB_APP_PRIVATE_KEY``
                        are not set in settings.
        """
        app_id = self._settings.github_app_id
        private_key = self._settings.github_app_private_key

        if not app_id or not private_key:
            raise ValueError(
                "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be set in environment variables."
            )

        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued-at slightly in the past to account for clock skew
            "exp": now + _APP_JWT_EXPIRY_SECONDS,
            "iss": str(app_id),
        }

        # The private key may be stored with literal `\n` in the env var.
        pem_key = private_key.replace("\\n", "\n")

        token: str = jwt.encode(payload, pem_key, algorithm="RS256")
        return token

    async def _mint_token(self, installation_id: int) -> str:
        """Exchange a GitHub App JWT for an installation access token.

        Args:
            installation_id: GitHub's numeric installation ID.

        Returns:
            The installation access token string.

        Raises:
            httpx.HTTPStatusError: On non-2xx GitHub API responses.
        """
        app_jwt = self._build_app_jwt()
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            data = response.json()

        token: str = data["token"]
        logger.debug("Minted new installation token for installation %d", installation_id)
        return token
