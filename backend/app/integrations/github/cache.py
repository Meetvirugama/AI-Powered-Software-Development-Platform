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

import collections
import json
import logging
import threading
import time
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class SourceRevisionCache:
    """Revision-safe cache for repository source code with bounded memory TTL and capacity.

    Ensures that content from commit A is never returned when commit B is
    requested, even if the file path is identical.

    Thread-safety: all in-memory mutations are guarded by an RLock so the cache
    can be safely accessed from multiple threads (e.g. via asyncio.to_thread).

    Eviction policy: true LRU via OrderedDict.move_to_end() on every cache hit,
    with proactive TTL expiration during eviction cycles.
    """

    def __init__(
        self,
        redis_client: Any = None,
        default_ttl_seconds: int = 3600,
        max_memory_entries: int = 1000,
    ) -> None:
        # OrderedDict gives us O(1) move_to_end for LRU and O(1) popitem for eviction
        self._memory_cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._memory_expires: dict[str, float] = {}
        self._redis = redis_client
        self._default_ttl = default_ttl_seconds
        self._max_memory_entries = max_memory_entries
        # Reentrant lock: safe for nested calls (e.g. get() calling invalidate())
        self._lock = threading.RLock()

    @staticmethod
    def build_key(repository_id: UUID | str, revision: str, path: str) -> str:
        """Construct a deterministic, revision-scoped cache key.

        Format: gh_src:{repository_id}:{revision}:{normalized_path}
        """
        clean_repo = str(repository_id).strip()
        clean_rev = revision.strip()
        clean_path = path.strip().lstrip("/")
        return f"gh_src:{clean_repo}:{clean_rev}:{clean_path}"

    def _purge_expired(self) -> None:
        """Proactively remove all expired entries from the in-memory cache.

        Called during eviction cycles so that stale entries free up capacity
        before evicting a live LRU entry. Caller must hold self._lock.
        """
        now = time.monotonic()
        # Collect expired keys in one pass, then remove them
        expired_keys = [k for k, exp in self._memory_expires.items() if now > exp]
        for k in expired_keys:
            self._memory_cache.pop(k, None)
            self._memory_expires.pop(k, None)

    def _evict_if_needed(self, incoming_key: str) -> None:
        """Make room for a new entry if the cache is at capacity.

        Strategy:
        1. If the key already exists, no eviction needed (it will be overwritten).
        2. Purge all TTL-expired entries first — they waste capacity.
        3. If still at capacity, pop the least-recently-used entry (front of OrderedDict).

        Caller must hold self._lock.
        """
        if incoming_key in self._memory_cache:
            return  # overwrite path — no eviction needed

        if len(self._memory_cache) >= self._max_memory_entries:
            # Step 1: sweep expired entries to free capacity without sacrificing live data
            self._purge_expired()

        if len(self._memory_cache) >= self._max_memory_entries:
            # Step 2: still full — evict the true LRU entry (front of OrderedDict)
            oldest_key, _ = self._memory_cache.popitem(last=False)
            self._memory_expires.pop(oldest_key, None)

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

        # 1. Try Memory Cache with TTL validation
        now = time.monotonic()
        with self._lock:
            exp = self._memory_expires.get(key)
            if exp is not None and now > exp:
                # Entry has expired — remove it immediately
                self._memory_cache.pop(key, None)
                self._memory_expires.pop(key, None)
                entry = None
            else:
                entry = self._memory_cache.get(key)
                if entry is not None:
                    # LRU promotion: move this key to the end (most recently used)
                    self._memory_cache.move_to_end(key)

        # 2. Try Redis if not found in memory
        if entry is None and self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    if raw.startswith("zlib:"):
                        import base64
                        import zlib
                        raw = zlib.decompress(base64.b64decode(raw[5:])).decode("utf-8")
                    entry = json.loads(raw)
                    # Populate memory cache with TTL
                    clean_rev = revision.strip()
                    if len(clean_rev) == 40 and all(c in "0123456789abcdefABCDEF" for c in clean_rev):
                        mem_ttl = 7 * 86400
                    else:
                        mem_ttl = 300
                    with self._lock:
                        self._evict_if_needed(key)
                        self._memory_cache[key] = entry
                        # Move to end (most recently used) after insert
                        self._memory_cache.move_to_end(key)
                        self._memory_expires[key] = now + mem_ttl
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
        if ttl_seconds is not None:
            ttl = ttl_seconds
        else:
            clean_rev = revision.strip()
            if len(clean_rev) == 40 and all(c in "0123456789abcdefABCDEF" for c in clean_rev):
                ttl = 7 * 86400  # 7 days for immutable commit SHAs (Audit B5.4)
            else:
                ttl = 300  # 5 minutes for mutable branch heads (Audit B5.4)
        now = time.monotonic()

        # Ensure revision metadata is explicitly attached to the entry
        entry = dict(data)
        entry["revision"] = revision
        if commit_sha:
            entry["commit_sha"] = commit_sha
        entry["cached_at_revision"] = revision

        # 1. Store in memory with capacity bounds and LRU ordering
        with self._lock:
            self._evict_if_needed(key)
            self._memory_cache[key] = entry
            # Place at end (most recently used)
            self._memory_cache.move_to_end(key)
            self._memory_expires[key] = now + ttl

        # 2. Store in Redis
        if self._redis is not None:
            try:
                serialized = json.dumps(entry)
                if len(serialized) > 8192:
                    import base64
                    import zlib
                    compressed = base64.b64encode(zlib.compress(serialized.encode("utf-8"))).decode("ascii")
                    payload = f"zlib:{compressed}"
                else:
                    payload = serialized
                self._redis.setex(key, ttl, payload)
            except Exception as exc:
                logger.warning("Redis cache write failed for key %s: %s", key, exc)

        # 3. If commit_sha is known and distinct from revision (e.g. revision was 'main'),
        # also cache under the immutable commit_sha for immutable content addressing
        if commit_sha and commit_sha != revision:
            immutable_key = self.build_key(repository_id, commit_sha, path)
            immutable_entry = dict(entry)
            immutable_entry["revision"] = commit_sha
            immutable_ttl = 7 * 86400
            with self._lock:
                self._evict_if_needed(immutable_key)
                self._memory_cache[immutable_key] = immutable_entry
                self._memory_cache.move_to_end(immutable_key)
                self._memory_expires[immutable_key] = now + immutable_ttl
            if self._redis is not None:
                try:
                    ser = json.dumps(immutable_entry)
                    if len(ser) > 8192:
                        import base64
                        import zlib
                        comp = base64.b64encode(zlib.compress(ser.encode("utf-8"))).decode("ascii")
                        im_payload = f"zlib:{comp}"
                    else:
                        im_payload = ser
                    self._redis.setex(immutable_key, immutable_ttl, im_payload)
                except Exception as exc:
                    logger.debug("Failed saving compressed payload to Redis cache: %s", exc)

    def invalidate(
        self,
        repository_id: UUID | str,
        revision: str,
        path: str,
    ) -> None:
        """Invalidate a specific cached file at a specific revision."""
        key = self.build_key(repository_id, revision, path)
        with self._lock:
            self._memory_cache.pop(key, None)
            self._memory_expires.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception as exc:
                logger.warning("Redis cache delete failed for key %s: %s", key, exc)

    def invalidate_revision(self, repository_id: UUID | str, revision: str) -> int:
        """Invalidate all cached files for a repository at a given revision."""
        prefix = f"gh_src:{str(repository_id).strip()}:{revision.strip()}:"
        with self._lock:
            matching_keys = [k for k in self._memory_cache if k.startswith(prefix)]
            for k in matching_keys:
                self._memory_cache.pop(k, None)
                self._memory_expires.pop(k, None)

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
        with self._lock:
            matching_keys = [k for k in self._memory_cache if k.startswith(prefix)]
            for k in matching_keys:
                self._memory_cache.pop(k, None)
                self._memory_expires.pop(k, None)

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
        with self._lock:
            self._memory_cache.clear()
            self._memory_expires.clear()
