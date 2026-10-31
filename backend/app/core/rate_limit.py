"""Per-route rate limiting backed by Redis.
Owner: Sukun — W1, Day 6 (API Security) / Extended by Yug — W2, Day 1–7

Limits (Docs/week1.md, Day 6 & Docs/week2.md, Section 4.6):
    /auth/github/callback                      10 req/min per IP
    /repositories/:id/sync                      5 req/min per user
    /repositories/:id/chat                     30 req/min per user
    /repositories/:id/explain                  20 req/min per user
    /repositories/:id/detect-bugs              20 req/min per user
    /repositories/:id/generate-tests           20 req/min per user
    /repositories/:id/review                   20 req/min per user
    /repositories/:id/source/agent-branch      20 req/min per user
    /repositories/:id/source/commit            20 req/min per user
    /repositories/:id/source/pr-metadata       20 req/min per user

Algorithm: fixed one-minute window. Each request increments
``ratelimit:<rule>:<identity>:<window>`` in Redis; the key expires on its own
after the window, so Redis never grows without bound. When the count passes
the limit the API returns ``429 RATE_LIMITED`` with a ``Retry-After`` header.

If Redis is unreachable the request is allowed (fail open) and a warning is
logged, so a Redis outage never takes the whole API down with it.

Middleware order matters: this middleware must run *inside* JWTMiddleware so
``request.state.user_id`` is already set for the per-user limits.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import error_response
from app.core import redis as redis_module

logger = logging.getLogger(__name__)

RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    methods: frozenset[str]
    path_pattern: re.Pattern[str]
    limit: int
    window_seconds: int
    per: Literal["ip", "user"]


def _rules(prefix: str) -> tuple[RateLimitRule, ...]:
    p = re.escape(prefix)
    return (
        # The OAuth callback is a GET redirect from GitHub in our implementation;
        # POST is included too so the limit still applies if it ever changes.
        RateLimitRule("auth_callback", frozenset({"GET", "POST"}),
                      re.compile(rf"^{p}/auth/github/callback/?$"), 10, 60, "ip"),
        RateLimitRule("repo_sync", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/sync/?$"), 5, 60, "user"),
        RateLimitRule("repo_chat", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/chat/?$"), 30, 60, "user"),
        RateLimitRule("repo_explain", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/explain/?$"), 20, 60, "user"),
        RateLimitRule("repo_detect_bugs", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/detect-bugs/?$"), 20, 60, "user"),
        RateLimitRule("repo_generate_tests", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/generate-tests/?$"), 20, 60, "user"),
        RateLimitRule("repo_review", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/review/?$"), 20, 60, "user"),
        RateLimitRule("repo_agent_branch", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/source/agent-branch/?$"), 20, 60, "user"),
        RateLimitRule("repo_source_commit", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/source/commit/?$"), 20, 60, "user"),
        RateLimitRule("repo_pr_metadata", frozenset({"POST"}),
                      re.compile(rf"^{p}/repositories/[^/]+/source/pr-metadata/?$"), 20, 60, "user"),
    )


class RateLimitStore(Protocol):
    def hit(self, key: str, window_seconds: int) -> int:
        """Increment ``key`` and return the new count within the window."""


class RedisRateLimitStore:
    def __init__(self, redis: object) -> None:
        self.redis = redis

    def hit(self, key: str, window_seconds: int) -> int:
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds + 5)  # small buffer; the key name already carries the window
        count, _ = pipe.execute()
        return int(count)


class InMemoryRateLimitStore:
    """Single-process store for tests and local runs without Redis."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def hit(self, key: str, window_seconds: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class BoundedInMemoryRateLimitStore:
    """Thread-safe bounded in-memory rate limit store for AI endpoint fallback during Redis outages (B-04).

    Ensures that per-user limits for expensive LLM operations continue to be enforced
    locally even when Redis is down, preventing runaway provider quota exhaustion.
    Prunes expired keys automatically to prevent unbounded memory growth.
    """

    def __init__(self, max_keys: int = 10_000) -> None:
        self._counts: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)
        self._max_keys = max_keys

    def hit(self, key: str, window_seconds: int) -> int:
        now = time.time()
        # Periodic pruning when table gets large
        if len(self._counts) >= self._max_keys:
            self._prune(now)

        entry = self._counts.get(key)
        if entry is None or now >= entry[1]:
            new_count = 1
            expires_at = now + window_seconds + 5
            self._counts[key] = (new_count, expires_at)
            return new_count

        new_count = entry[0] + 1
        self._counts[key] = (new_count, entry[1])
        return new_count

    def _prune(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._counts.items() if now >= exp]
        for k in expired:
            self._counts.pop(k, None)
        if len(self._counts) >= self._max_keys:
            # Evict oldest 25% of keys if still at cap
            oldest = list(self._counts.keys())[: self._max_keys // 4]
            for k in oldest:
                self._counts.pop(k, None)

    def reset(self) -> None:
        self._counts.clear()


AI_EXPENSIVE_RULES: frozenset[str] = frozenset({
    "repo_chat",
    "repo_explain",
    "repo_detect_bugs",
    "repo_generate_tests",
    "repo_review",
})

_fallback_ai_store = BoundedInMemoryRateLimitStore()


def get_rate_limit_store() -> RateLimitStore:
    """Return the store used by the middleware. Tests monkeypatch this."""
    return RedisRateLimitStore(redis_module.get_redis())


def client_ip(request: Request) -> str:
    """The caller's IP. X-Forwarded-For is trusted only behind a known proxy."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_prefix: str = "/api/v1") -> None:
        super().__init__(app)
        self.rules = _rules(api_prefix)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not get_settings().rate_limit_enabled:
            return await call_next(request)

        rule = self._match(request)
        if rule is None:
            return await call_next(request)

        if rule.per == "user":
            user_id = getattr(request.state, "user_id", None)
            if not user_id:
                # Unauthenticated requests are already rejected by JWTMiddleware.
                return await call_next(request)
            identity = f"user:{user_id}"
        else:
            identity = f"ip:{client_ip(request)}"

        now = time.time()
        window = int(now // rule.window_seconds)
        key = f"ratelimit:{rule.name}:{identity}:{window}"

        is_ai_rule = rule.name in AI_EXPENSIVE_RULES
        redis_failed = False

        try:
            store = get_rate_limit_store()
            hit_fn = getattr(store, "hit", None)
            if hit_fn is None:
                count = 1
            elif inspect.iscoroutinefunction(hit_fn):
                count = await asyncio.wait_for(hit_fn(key, rule.window_seconds), timeout=1.0)
            else:
                res = await asyncio.wait_for(
                    asyncio.to_thread(hit_fn, key, rule.window_seconds),
                    timeout=1.0,
                )
                if inspect.isawaitable(res):
                    count = await asyncio.wait_for(res, timeout=1.0)
                else:
                    count = int(res)
        except Exception as exc:  # noqa: BLE001
            redis_failed = True
            logger.warning(
                "rate_limit_store_unavailable",
                extra={
                    "rule": rule.name,
                    "identity": identity,
                    "is_ai_rule": is_ai_rule,
                    "error": str(exc),
                },
            )
            if is_ai_rule:
                # B-04 Fix: Enforce bounded in-memory rate limiting for expensive AI endpoints during Redis outages
                count = _fallback_ai_store.hit(key, rule.window_seconds)
            else:
                # Non-AI endpoints fail open to preserve general site availability
                return await call_next(request)

        remaining = max(0, rule.limit - count)
        reset_in = max(1, int((window + 1) * rule.window_seconds - now))

        if count > rule.limit:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "rule": rule.name,
                    "identity": identity,
                    "redis_failed": redis_failed,
                    "fallback_active": is_ai_rule and redis_failed,
                },
            )
            response = error_response(
                429, RATE_LIMITED,
                f"Too many requests. Try again in {reset_in} seconds.",
                retryable=True,
            )
            response.headers["Retry-After"] = str(reset_in)
        else:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(rule.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)
        if redis_failed and is_ai_rule:
            response.headers["X-RateLimit-Fallback"] = "local-in-memory"
        return response

    def _match(self, request: Request) -> RateLimitRule | None:
        path = request.url.path
        for rule in self.rules:
            if request.method in rule.methods and rule.path_pattern.match(path):
                return rule
        return None
