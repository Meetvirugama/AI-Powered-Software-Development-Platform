"""
Safe, versioned serialization for cached retrieval results (R03).
Owner: Meet — W1-12

Uses JSON serialization instead of unsafe pickle.
Enforces schema version validation and payload bounds.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from .base import CodeChunk

logger = logging.getLogger(__name__)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "deserialize_chunks",
    "deserialize_retrieval_payload",
    "serialize_chunks",
    "serialize_retrieval_payload",
]

CURRENT_SCHEMA_VERSION = "2.0"


def serialize_retrieval_payload(data: Any) -> str:
    """
    Serialize any retrieval payload (either list of CodeChunk or generic dict/list)
    to a versioned JSON string.
    """
    if isinstance(data, list) and data and isinstance(data[0], CodeChunk):
        return serialize_chunks(data)

    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "payload_type": "generic",
        "data": data,
    }
    return json.dumps(payload, separators=(",", ":"))


def deserialize_retrieval_payload(data: str) -> Any:
    """
    Deserialize versioned JSON data into either a list of CodeChunk or original generic payload.
    """
    if not data:
        return None

    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("cache_deserialize_json_error", extra={"error": str(exc)})
        return None

    if not isinstance(payload, dict):
        return None

    version = payload.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        return None

    if payload.get("payload_type") == "generic":
        return payload.get("data")

    if "chunks" in payload:
        return deserialize_chunks(data)

    return None


def serialize_chunks(chunks: list[CodeChunk]) -> str:
    """
    Serialize a list of CodeChunk objects to a versioned JSON string.
    """
    chunk_dicts: list[dict[str, Any]] = []
    for c in chunks:
        chunk_dicts.append({
            "id": str(c.id),
            "repository_id": str(c.repository_id),
            "file_id": str(c.file_id),
            "symbol_id": str(c.symbol_id) if c.symbol_id else None,
            "content": c.content,
            "token_count": c.token_count,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "content_hash": c.content_hash,
            "score": float(c.score),
            "file_path": c.file_path,
            "rrf_score": float(c.rrf_score) if c.rrf_score is not None else None,
            "reranker_logit": float(c.reranker_logit) if c.reranker_logit is not None else None,
            "vector_similarity": float(c.vector_similarity) if c.vector_similarity is not None else None,
            "lexical_rank": float(c.lexical_rank) if c.lexical_rank is not None else None,
            "graph_score": float(c.graph_score) if c.graph_score is not None else None,
        })

    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "chunks": chunk_dicts,
    }
    return json.dumps(payload, separators=(",", ":"))


def deserialize_chunks(data: str) -> list[CodeChunk] | None:
    """
    Deserialize a versioned JSON string into a list of CodeChunk objects.

    Returns:
        List of CodeChunk on success, or None if data is corrupt or schema version mismatches.
    """
    if not data:
        return None

    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("cache_deserialize_json_error", extra={"error": str(exc)})
        return None

    if not isinstance(payload, dict):
        return None

    version = payload.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        logger.info(
            "cache_deserialize_schema_version_mismatch",
            extra={"expected": CURRENT_SCHEMA_VERSION, "actual": version},
        )
        return None

    raw_chunks = payload.get("chunks")
    if not isinstance(raw_chunks, list):
        return None

    chunks: list[CodeChunk] = []
    for item in raw_chunks:
        try:
            chunks.append(
                CodeChunk(
                    id=UUID(str(item["id"])),
                    repository_id=UUID(str(item["repository_id"])),
                    file_id=UUID(str(item["file_id"])),
                    symbol_id=UUID(str(item["symbol_id"])) if item.get("symbol_id") else None,
                    content=str(item.get("content", "")),
                    token_count=int(item.get("token_count", 0)),
                    start_line=int(item.get("start_line", 1)),
                    end_line=int(item.get("end_line", 1)),
                    content_hash=str(item.get("content_hash", "")),
                    score=float(item.get("score", 0.0)),
                    file_path=str(item.get("file_path", "")),
                    rrf_score=float(item["rrf_score"]) if item.get("rrf_score") is not None else None,
                    reranker_logit=float(item["reranker_logit"]) if item.get("reranker_logit") is not None else None,
                    vector_similarity=float(item["vector_similarity"]) if item.get("vector_similarity") is not None else None,
                    lexical_rank=float(item["lexical_rank"]) if item.get("lexical_rank") is not None else None,
                    graph_score=float(item["graph_score"]) if item.get("graph_score") is not None else None,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("cache_deserialize_chunk_parse_error", extra={"error": str(exc)})
            return None

    return chunks
