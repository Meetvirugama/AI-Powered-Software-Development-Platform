"""Repository Review Settings Persistence Service.

Provides repository-level code review and PR publication settings management,
backed by Redis with an in-memory dictionary fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_SETTINGS: dict[str, Any] = {
    "min_confidence": "medium",
    "max_comments": 15,
    "changed_lines_only": True,
}

_in_memory_settings: dict[str, dict[str, Any]] = {}


def _make_key(repo_id: str | UUID) -> str:
    return f"repo_review_settings:{str(repo_id)}"


def get_repo_review_settings(repo_id: str | UUID) -> dict[str, Any]:
    """Retrieve persisted review settings for a repository, falling back to defaults."""
    repo_key = _make_key(repo_id)
    cached_data: dict[str, Any] | None = None

    try:
        from app.core.redis import get_redis

        r = get_redis()
        if r is not None:
            raw = r.get(repo_key)
            if raw:
                cached_data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except Exception as exc:
        logger.debug("Failed to read repo review settings from Redis: %s", exc)

    if cached_data is None:
        cached_data = _in_memory_settings.get(str(repo_id), {})

    merged = {
        "min_confidence": str(cached_data.get("min_confidence") or DEFAULT_REVIEW_SETTINGS["min_confidence"]).lower(),
        "max_comments": int(cached_data.get("max_comments", DEFAULT_REVIEW_SETTINGS["max_comments"])),
        "changed_lines_only": bool(
            cached_data["changed_lines_only"]
            if "changed_lines_only" in cached_data and cached_data["changed_lines_only"] is not None
            else DEFAULT_REVIEW_SETTINGS["changed_lines_only"]
        ),
    }
    return merged


def set_repo_review_settings(repo_id: str | UUID, settings: dict[str, Any]) -> dict[str, Any]:
    """Update and persist review settings for a repository."""
    repo_key = _make_key(repo_id)
    current = get_repo_review_settings(repo_id)

    if "min_confidence" in settings and settings["min_confidence"] is not None:
        current["min_confidence"] = str(settings["min_confidence"]).lower()
    if "max_comments" in settings and settings["max_comments"] is not None:
        current["max_comments"] = int(settings["max_comments"])
    if "changed_lines_only" in settings and settings["changed_lines_only"] is not None:
        current["changed_lines_only"] = bool(settings["changed_lines_only"])

    _in_memory_settings[str(repo_id)] = dict(current)

    try:
        from app.core.redis import get_redis

        r = get_redis()
        if r is not None:
            r.set(repo_key, json.dumps(current))
    except Exception as exc:
        logger.debug("Failed to persist repo review settings to Redis: %s", exc)

    return current
