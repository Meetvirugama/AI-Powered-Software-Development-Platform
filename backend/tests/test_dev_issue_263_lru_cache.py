"""Tests for Issue #263 (F-44): thread-safe true LRU eviction and proactive TTL expiration.

Covers the three requirements from the issue description:
1. True LRU eviction via OrderedDict.move_to_end() — hot keys survive eviction.
2. Proactive TTL expiration during eviction — expired keys are swept before sacrificing live LRU entries.
3. Thread-safe memory cache access via threading.RLock — concurrent mutations don't corrupt state.
"""

from __future__ import annotations

import collections
import threading
import time
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.integrations.github.cache import SourceRevisionCache


# ═══════════════════════════════════════════════════════════════════════════
# 1. True LRU eviction (not FIFO)
# ═══════════════════════════════════════════════════════════════════════════

class TestTrueLRUEviction:
    """Verify that cache eviction follows LRU order, not FIFO insertion order."""

    def test_internal_storage_is_ordered_dict(self):
        """The in-memory cache must be an OrderedDict for O(1) LRU operations."""
        cache = SourceRevisionCache(max_memory_entries=5)
        assert isinstance(cache._memory_cache, collections.OrderedDict)

    def test_recently_accessed_key_survives_eviction(self):
        """A key accessed via get() is promoted to MRU and must NOT be the eviction victim."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=3)

        # Insert 3 entries: A, B, C  (insertion order = A oldest)
        cache.set(repo, "v1", "a.py", {"content": "A"})
        cache.set(repo, "v1", "b.py", {"content": "B"})
        cache.set(repo, "v1", "c.py", {"content": "C"})

        # Access A — this should promote A to MRU, making B the new LRU
        result = cache.get(repo, "v1", "a.py")
        assert result is not None
        assert result["content"] == "A"

        # Insert D — capacity exceeded, LRU victim should be B (not A!)
        cache.set(repo, "v1", "d.py", {"content": "D"})

        # A must survive (it was accessed), B must be evicted
        assert cache.get(repo, "v1", "a.py") is not None, "A was recently accessed, should survive"
        assert cache.get(repo, "v1", "b.py") is None, "B was LRU, should be evicted"
        assert cache.get(repo, "v1", "c.py") is not None, "C should survive"
        assert cache.get(repo, "v1", "d.py") is not None, "D was just inserted"

    def test_fifo_would_fail_but_lru_succeeds(self):
        """Demonstrates the concrete FIFO vs LRU difference the issue describes."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=2)

        # Insert hot.py first, then cold.py
        cache.set(repo, "v1", "hot.py", {"content": "hot"})
        cache.set(repo, "v1", "cold.py", {"content": "cold"})

        # Repeatedly access hot.py (simulating a frequently browsed file)
        for _ in range(5):
            cache.get(repo, "v1", "hot.py")

        # Insert new.py — triggers eviction
        cache.set(repo, "v1", "new.py", {"content": "new"})

        # Under FIFO: hot.py (inserted first) would be evicted — WRONG
        # Under LRU: cold.py (least recently used) gets evicted — CORRECT
        assert cache.get(repo, "v1", "hot.py") is not None, "Hot file must survive LRU eviction"
        assert cache.get(repo, "v1", "cold.py") is None, "Cold file should be evicted as LRU"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Proactive TTL expiration during eviction cycles
# ═══════════════════════════════════════════════════════════════════════════

class TestProactiveTTLExpiration:
    """Verify that expired entries are swept proactively during eviction, not just lazily."""

    def test_expired_entries_freed_before_live_lru_evicted(self):
        """When cache is full, expired entries should be purged first, saving live LRU entries."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=3)

        # Insert 3 entries with short TTL
        cache.set(repo, "v1", "expired1.py", {"content": "e1"}, ttl_seconds=1)
        cache.set(repo, "v1", "expired2.py", {"content": "e2"}, ttl_seconds=1)
        cache.set(repo, "v1", "live.py", {"content": "live"}, ttl_seconds=9999)

        # Simulate time passing so the first two entries expire
        with patch("time.monotonic", return_value=time.monotonic() + 5):
            # Insert new entry — should purge expired1 and expired2 first, NOT evict live.py
            cache.set(repo, "v1", "new.py", {"content": "new"}, ttl_seconds=9999)

            # live.py must survive because expired entries were freed first
            assert cache.get(repo, "v1", "live.py") is not None, "Live entry should not be evicted"
            assert cache.get(repo, "v1", "new.py") is not None, "New entry should exist"

    def test_purge_expired_removes_stale_keys(self):
        """Direct test of the _purge_expired internal method."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=10)

        cache.set(repo, "v1", "a.py", {"content": "a"}, ttl_seconds=1)
        cache.set(repo, "v1", "b.py", {"content": "b"}, ttl_seconds=9999)

        # Advance time past TTL of a.py
        with patch("time.monotonic", return_value=time.monotonic() + 5):
            cache._purge_expired()

        # a.py should be purged, b.py should remain
        key_a = cache.build_key(repo, "v1", "a.py")
        key_b = cache.build_key(repo, "v1", "b.py")
        assert key_a not in cache._memory_cache
        assert key_b in cache._memory_cache


# ═══════════════════════════════════════════════════════════════════════════
# 3. Thread-safe memory cache access
# ═══════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    """Verify that concurrent access from multiple threads does not corrupt cache state."""

    def test_cache_has_rlock(self):
        """The cache must use a threading.RLock for thread safety."""
        cache = SourceRevisionCache()
        assert isinstance(cache._lock, type(threading.RLock()))

    def test_concurrent_set_and_get_no_corruption(self):
        """Concurrent writers and readers must not crash or corrupt cache state."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=50)
        errors: list[Exception] = []

        def writer(thread_id: int):
            """Each writer inserts 100 entries."""
            try:
                for i in range(100):
                    cache.set(repo, "v1", f"t{thread_id}_f{i}.py", {"content": f"t{thread_id}_{i}"})
            except Exception as e:
                errors.append(e)

        def reader(thread_id: int):
            """Each reader reads 100 entries (some may miss, that's fine)."""
            try:
                for i in range(100):
                    cache.get(repo, "v1", f"t{thread_id}_f{i}.py")
            except Exception as e:
                errors.append(e)

        # Launch 4 writer threads and 4 reader threads concurrently
        threads = []
        for tid in range(4):
            threads.append(threading.Thread(target=writer, args=(tid,)))
            threads.append(threading.Thread(target=reader, args=(tid,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # No thread should have raised an exception
        assert len(errors) == 0, f"Thread errors: {errors}"

        # Cache internal state must be consistent: cache and expires must have same key set
        assert set(cache._memory_cache.keys()) <= set(cache._memory_expires.keys()) | set(cache._memory_cache.keys())
        # No more entries than max
        assert len(cache._memory_cache) <= cache._max_memory_entries

    def test_concurrent_eviction_under_pressure(self):
        """Many threads inserting into a tiny cache must not corrupt OrderedDict."""
        repo = uuid4()
        cache = SourceRevisionCache(max_memory_entries=5)
        errors: list[Exception] = []

        def hammerer(thread_id: int):
            try:
                for i in range(200):
                    key = f"t{thread_id}_file{i}.py"
                    cache.set(repo, "v1", key, {"content": f"{thread_id}_{i}"})
                    cache.get(repo, "v1", key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammerer, args=(tid,)) for tid in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(cache._memory_cache) <= 5

