import hashlib


def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hash of file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def should_reindex(
    content: str,
    existing_hash: str | None,
) -> bool:
    """Return True when a file is new or its content has changed."""
    if existing_hash is None:
        return True

    return compute_content_hash(content) != existing_hash