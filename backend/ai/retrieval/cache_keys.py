"""
Stable cache-key generation for hybrid retrieval results (R03, R04).
Owner: Meet — W1-12

Distinguishes:
- tenant / access scope
- repository ID
- active index generation or commit SHA
- query intent
- normalized query hash (SHA-256)
- candidate & final limits (top_k, vector_top_k, lexical_top_k)
- pipeline component versions (embedding, chunker, tokenizer, rrf, reranker)
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
    "normalize_retrieval_query",
]

DEFAULT_VERSIONS = {
    "embedding_version": "v1",
    "chunker_version": "v1",
    "tokenizer_version": "v1",
    "retrieval_version": "v2",
    "rrf_version": "v2",
    "reranker_version": "ms-marco-v1",
}


def normalize_retrieval_query(query: str) -> str:
    """Normalize query text: strip whitespace, lowercase, collapse internal whitespace."""
    if not query:
        return ""
    q = query.strip().lower()
    return re.sub(r"\s+", " ", q)


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
) -> str:
    """
    Construct a stable, collision-resistant Redis key for hybrid retrieval results.

    Format:
        retrieval:v2:{scope}:{repository_id}:{index_generation}:{query_hash}

    Never contains raw source code or unhashed query strings.
    """
    repo_str = str(repository_id)
    norm_query = normalize_retrieval_query(query)
    gen_str = str(index_generation)
    active_versions = {**DEFAULT_VERSIONS, **(versions or {})}

    key_payload: dict[str, Any] = {
        "norm_query": norm_query,
        "intent": str(intent).lower(),
        "top_k": int(top_k),
        "vector_top_k": int(vector_top_k),
        "lexical_top_k": int(lexical_top_k),
        "versions": active_versions,
    }

    # Deterministic JSON representation for SHA-256 hashing
    canonical_json = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
    query_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:32]

    return f"retrieval:v2:{scope}:{repo_str}:{gen_str}:{query_hash}"
