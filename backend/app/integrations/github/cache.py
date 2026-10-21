"""Source revision cache for GitHub repository files.

Deliverable for Parth — Week 2 Day 2: Source Revision Correctness.
Critical Guarantee:
    Prevent cached content from silently representing a different revision.

Key mechanisms:
1. Revision-scoped cache keys:
   Keys are strictly bound to (repository_id, revision, path) or immutable blob SHA.
2. In-memory and Redis-backed storage with automatic serialization.
3. Revision integrity validation:
   On cache retrieval, the cached revision/commit_sha is verified against the
   requested revision. If there is any discrepancy, the cache entry is rejected
   (cache miss/evicted) so stale or cross-revision data is NEVER silently served.
4. Fine-grained invalidation:
   Support invalidating by repository, revision, or individual file path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class RevisionMismatchError(Exception):
    """Raised when a cached entry does not match the requested revision."""

    def __init__(self, requested: str, found: str, path: str) -> None:
        super().__init__(
            f"Cache revision mismatch for '{path}': requested '{requested}', found '{found}'."
        )
        self.requested = requested
        self.found = found
        self.path = path


class SourceRevisionCache:
    """Revision-safe cache for repository source code.

    Ensures that content from commit A is never returned when commit B is
    requested, even if the file path is identical.
    """

    def __init__(self, redis_client: Any = None, default_ttl_seconds: int = 3600) -> None:
        self._memory_cache: dict[str, dict[str, Any]] = {}
        self._redis = redis_client
        self._default_ttl = default_ttl_seconds

    @staticmethod
    def build_key(repository_id: UUID | str, revision: str, path: str) -> str:
        """Construct a deterministic, revision-scoped cache key.

        Format: gh_src:{repository_id}:{revision}:{normalized_path}
        """
        clean_repo = str(repository_id).strip()
        clean_rev = revision.strip()
        clean_path = path.strip().lstrip("/")
        return f"gh_src:{clean_repo}:{clean_rev}:{clean_path}"

    def get(
        self,
        repository_id: UUID | str,
        revision: str,
        path: str,
        expected_commit_sha: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a cached file entry, validating revision correctness.

        Parameters
        ----------
        repository_id : UUID | str
            Target repository ID.
        revision : str
            The requested revision (branch, tag, or commit SHA).
        path : str
            Repository file path.
        expected_commit_sha : str | None
            If provided, verifies the cached entry's commit SHA matches.

        Returns
        -------
        dict[str, Any] | None
            The cached file data, or None if missing/invalidated.
        """
        key = self.build_key(repository_id, revision, path)

        # 1. Try Memory Cache
        entry = self._memory_cache.get(key)

        # 2. Try Redis if not found in memory
        if entry is None and self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    entry = json.loads(raw)
                    # Populate memory cache
                    self._memory_cache[key] = entry
            except Exception as exc:
                logger.warning("Redis cache read failed for key %s: %s", key, exc)

        if entry is None:
            return None

        # 3. CRITICAL: Validate revision integrity
        cached_rev = entry.get("revision")
        cached_commit = entry.get("commit_sha")
        cached_blob = entry.get("blob_sha") or entry.get("sha")

        # The entry must match the requested revision
        valid = False
        if cached_rev == revision or cached_commit == revision or cached_blob == revision:
            valid = True

        if expected_commit_sha and cached_commit and cached_commit != expected_commit_sha:
            valid = False

        if not valid:
            logger.error(
                "Prevented cache revision leak for %s: requested '%s', cached has rev='%s', commit='%s'",
                path,
                revision,
                cached_rev,
                cached_commit,
            )
            # Invalidate corrupt / mismatched entry
            self.invalidate(repository_id, revision, path)
            return None

        return entry

    def set(
        self,
        repository_id: UUID | str,
        revision: str,
        path: str,
        data: dict[str, Any],
        commit_sha: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store file content in the revision-safe cache.

        Always embeds the revision and commit_sha within the payload for
        validation upon retrieval.
        """
        key = self.build_key(repository_id, revision, path)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        # Ensure revision metadata is explicitly attached to the entry
        entry = dict(data)
        entry["revision"] = revision
        if commit_sha:
            entry["commit_sha"] = commit_sha
        entry["cached_at_revision"] = revision

        # 1. Store in memory
        self._memory_cache[key] = entry

        # 2. Store in Redis
        if self._redis is not None:
            try:
                serialized = json.dumps(entry)
                self._redis.setex(key, ttl, serialized)
            except Exception as exc:
                logger.warning("Redis cache write failed for key %s: %s", key, exc)

        # 3. If commit_sha is known and distinct from revision (e.g. revision was 'main'),
        # also cache under the immutable commit_sha for immutable content addressing
        if commit_sha and commit_sha != revision:
            immutable_key = self.build_key(repository_id, commit_sha, path)
            immutable_entry = dict(entry)
            immutable_entry["revision"] = commit_sha
            self._memory_cache[immutable_key] = immutable_entry
            if self._redis is not None:
                try:
                    self._redis.setex(immutable_key, ttl, json.dumps(immutable_entry))
                except Exception:
                    pass

    def invalidate(
        self,
        repository_id: UUID | str,
        revision: str,
        path: str,
    ) -> None:
        """Invalidate a specific cached file at a specific revision."""
        key = self.build_key(repository_id, revision, path)
        self._memory_cache.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception as exc:
                logger.warning("Redis cache delete failed for key %s: %s", key, exc)

    def invalidate_revision(self, repository_id: UUID | str, revision: str) -> int:
        """Invalidate all cached files for a repository at a given revision."""
        prefix = f"gh_src:{str(repository_id).strip()}:{revision.strip()}:"
        matching_keys = [k for k in self._memory_cache if k.startswith(prefix)]
        for k in matching_keys:
            self._memory_cache.pop(k, None)

        if self._redis is not None:
            try:
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(cursor=cursor, match=f"{prefix}*", count=100)
                    if keys:
                        self._redis.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as exc:
                logger.warning("Redis revision invalidation failed for %s: %s", prefix, exc)

        return len(matching_keys)

    def invalidate_repository(self, repository_id: UUID | str) -> int:
        """Invalidate all cached revisions for a repository."""
        prefix = f"gh_src:{str(repository_id).strip()}:"
        matching_keys = [k for k in self._memory_cache if k.startswith(prefix)]
        for k in matching_keys:
            self._memory_cache.pop(k, None)

        if self._redis is not None:
            try:
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(cursor=cursor, match=f"{prefix}*", count=100)
                    if keys:
                        self._redis.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as exc:
                logger.warning("Redis repository invalidation failed for %s: %s", prefix, exc)

        return len(matching_keys)

    def clear(self) -> None:
        """Clear the in-memory cache entirely."""
        self._memory_cache.clear()
