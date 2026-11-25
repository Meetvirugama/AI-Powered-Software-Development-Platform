"""Shared pooled outbound HTTP clients bound to the active asyncio event loop."""

from __future__ import annotations

import asyncio
import threading
import weakref

import httpx

_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    weakref.WeakKeyDictionary()
)
_clients_lock = threading.Lock()


def get_shared_http_client() -> httpx.AsyncClient:
    """Return a shared, connection-pooled ``httpx.AsyncClient`` for the running loop.

    One client is kept per event loop because ``httpx`` connection pools are bound
    to a specific loop and worker/background paths occasionally execute via
    ``asyncio.run()`` on separate threads. This module-level pool serves as the
    shared client for ``GitHubService``, ``GitHubClient``, ``InstallationTokenManager``,
    and GitHub OAuth / installation-linking helpers so consecutive GitHub API calls
    reuse keep-alive TLS connections instead of performing a fresh handshake each time.
    """
    loop = asyncio.get_running_loop()
    with _clients_lock:
        client = _clients.get(loop)
        if client is not None and not client.is_closed:
            return client
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0,
            ),
        )
        _clients[loop] = client
        return client


async def close_shared_http_client() -> None:
    """Close and remove the shared ``httpx.AsyncClient`` for the current event loop."""
    loop = asyncio.get_running_loop()
    with _clients_lock:
        client = _clients.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()


__all__ = ["close_shared_http_client", "get_shared_http_client"]
