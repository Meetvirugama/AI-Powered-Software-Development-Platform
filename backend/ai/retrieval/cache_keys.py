"""
Stable cache-key generation for hybrid retrieval results (R03, R04).
Owner: Meet — W1-12
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

__all__ = [
    "DEFAULT_VERSIONS",
    "build_retrieval_cache_key",
    "generate_query_hash",
    "get_repository_index_version",
    "get_repository_index_version_async",
    "normalize_retrieval_query",
    "set_repository_index_version",
    "set_repository_index_version_async",
    "bump_repository_index_version_async",
]

DEFAULT_VERSIONS = {
    "embedding_version": "v1",
    "chunker_version": "v1",
    "tokenizer_version": "v1",
    "retrieval_version": "v2",
    "rrf_version": "v2",
    "reranker_version": "ms-marco-v1",
}

_LOCAL_REPO_INDEX_VERSIONS: dict[str, str] = {}


def _decode_redis_str(val: Any) -> str:
    """Safely normalize Redis bytes or string return values to clean UTF-8 strings."""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def normalize_retrieval_query(query: str) -> str:
    """Normalize query text: strip whitespace, lowercase, collapse internal whitespace."""
    if not query:
        return ""
    q = query.strip().lower()
    return re.sub(r"\s+", " ", q)


def generate_query_hash(
    query: str,
    retrieval_config: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic SHA-256 hash across normalized query text and parameters."""
    norm_query = normalize_retrieval_query(query)
    cfg = retrieval_config or {}
    payload: dict[str, Any] = {
        "norm_query": norm_query,
        "intent": str(cfg.get("intent", "conceptual")).lower(),
        "top_k": int(cfg.get("top_k", 8)),
        "vector_top_k": int(cfg.get("vector_top_k", 30)),
        "lexical_top_k": int(cfg.get("lexical_top_k", 30)),
        "versions": {**DEFAULT_VERSIONS, **(cfg.get("versions") or {})},
    }
    if "filters" in cfg and cfg["filters"]:
        payload["filters"] = cfg["filters"]
    if "embedding_model" in cfg and cfg["embedding_model"]:
        payload["embedding_model"] = str(cfg["embedding_model"])

    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:32]


def build_retrieval_cache_key(
    query: str,
    repository_id: UUID | str,
    index_generation: int | str = 0,
    intent: str = "conceptual",
    top_k: int = 8,
    vector_top_k: int = 30,
    lexical_top_k: int = 30,
    scope: str = "default",
    versions: dict[str, str] | None = None,
    *,
    index_version: int | str | None = None,
    filters: dict[str, Any] | None = None,
) -> str:
    """Construct a stable, collision-resistant Redis key for hybrid retrieval results."""
    repo_str = str(repository_id)
    effective_version = str(index_version if index_version is not None else index_generation)

    config_payload = {
        "intent": intent,
        "top_k": top_k,
        "vector_top_k": vector_top_k,
        "lexical_top_k": lexical_top_k,
        "versions": versions,
        "filters": filters,
    }
    query_hash = generate_query_hash(query, config_payload)

    return f"retrieval:v2:{scope}:{repo_str}:{effective_version}:{query_hash}"


async def get_repository_index_version_async(
    repo_id: str | UUID,
    redis_client: Any = None,
) -> str:
    """Resolve active repository index version asynchronously from Redis or local memory."""
    repo_str = str(repo_id)
    if redis_client is not None:
        try:
            val = await redis_client.get(f"retrieval:index_version:{repo_str}")
            if val:
                return _decode_redis_str(val)
        except Exception:
            pass
    return _LOCAL_REPO_INDEX_VERSIONS.get(repo_str, "0")


def get_repository_index_version(
    repo_id: str | UUID,
    redis_client: Any = None,
) -> str:
    """Resolve active repository index version synchronously from local memory or sync Redis."""
    repo_str = str(repo_id)
    if redis_client is not None and hasattr(redis_client, "get"):
        try:
            val = redis_client.get(f"retrieval:index_version:{repo_str}")
            if val:
                return _decode_redis_str(val)
        except Exception:
            pass
    return _LOCAL_REPO_INDEX_VERSIONS.get(repo_str, "0")


async def set_repository_index_version_async(
    repo_id: str | UUID,
    new_version: str,
    redis_client: Any = None,
) -> str:
    """Update active repository index version across distributed workers."""
    repo_str = str(repo_id)
    v_str = str(new_version)
    _LOCAL_REPO_INDEX_VERSIONS[repo_str] = v_str
    if redis_client is not None:
        try:
            await redis_client.set(f"retrieval:index_version:{repo_str}", v_str, ex=2592000)
        except Exception:
            pass
    return v_str


def set_repository_index_version(
    repo_id: str | UUID,
    new_version: str,
    redis_client: Any = None,
) -> str:
    """Update active repository index version synchronously."""
    repo_str = str(repo_id)
    v_str = str(new_version)
    _LOCAL_REPO_INDEX_VERSIONS[repo_str] = v_str
    if redis_client is not None and hasattr(redis_client, "set"):
        try:
            redis_client.set(f"retrieval:index_version:{repo_str}", v_str, ex=2592000)
        except Exception:
            pass
    return v_str


async def bump_repository_index_version_async(
    repo_id: str | UUID,
    redis_client: Any = None,
) -> str:
    """Advance the repository index version to a new timestamped generation."""
    import time
    new_ver = f"v{int(time.time() * 1000)}"
    return await set_repository_index_version_async(repo_id, new_ver, redis_client)
