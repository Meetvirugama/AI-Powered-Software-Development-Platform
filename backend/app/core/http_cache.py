"""HTTP conditional caching (ETag / 304 Not Modified) helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request, Response


def compute_etag(*parts: Any) -> str:
    """Compute a weak ETag over the provided state parts."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f'W/"{digest}"'


def _strip_weak_prefix(tag: str) -> str:
    stripped = tag.strip()
    if stripped.startswith("W/") or stripped.startswith("w/"):
        return stripped[2:].strip()
    return stripped


def etag_matches(request: Request, etag: str) -> bool:
    """Return True if ``If-None-Match`` matches ``etag``."""
    header = request.headers.get("if-none-match")
    if not header:
        return False
    target = _strip_weak_prefix(etag)
    for candidate in header.split(","):
        token = candidate.strip()
        if not token:
            continue
        if token == "*":
            return True
        if _strip_weak_prefix(token) == target:
            return True
    return False


def apply_cache_headers(response: Response, etag: str) -> None:
    """Attach private conditional caching headers to a 200 response."""
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["Vary"] = "Cookie, Authorization"


def not_modified(etag: str) -> Response:
    """Build a 304 Not Modified response with matching conditional cache headers."""
    return Response(
        status_code=304,
        headers={
            "ETag": etag,
            "Cache-Control": "private, no-cache",
            "Vary": "Cookie, Authorization",
        },
    )


def repository_index_token(repo: Any) -> str | None:
    """Return a version token representing the repository's current indexed state."""
    commit_sha = getattr(repo, "last_indexed_commit_sha", None)
    last_synced_at = getattr(repo, "last_synced_at", None)
    if commit_sha is None and last_synced_at is None:
        return None
    generation = getattr(repo, "active_index_generation", None)
    sync_status = getattr(repo, "sync_status", None)
    if hasattr(sync_status, "value"):
        sync_status = sync_status.value
    synced_str = last_synced_at.isoformat() if hasattr(last_synced_at, "isoformat") else last_synced_at
    return f"{commit_sha or ''}|{generation or ''}|{synced_str or ''}|{sync_status or ''}"


__all__ = [
    "apply_cache_headers",
    "compute_etag",
    "etag_matches",
    "not_modified",
    "repository_index_token",
]
