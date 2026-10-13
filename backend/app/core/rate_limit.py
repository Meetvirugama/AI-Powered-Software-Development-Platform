"""Per-route rate limiting backed by Redis.
Owner: Sukun — W1, Day 6 (API Security)

Limits (Docs/week1.md, Day 6):
    /auth/github/callback         10 req/min per IP
    /repositories/:id/sync         5 req/min per user
    /repositories/:id/chat        30 req/min per user

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

        try:
            count = get_rate_limit_store().hit(key, rule.window_seconds)
        except Exception:  # noqa: BLE001 — Redis down: fail open, never fail the request
            logger.warning("rate_limit_store_unavailable", extra={"rule": rule.name})
            return await call_next(request)

        remaining = max(0, rule.limit - count)
        reset_in = max(1, int((window + 1) * rule.window_seconds - now))

        if count > rule.limit:
            logger.warning("rate_limit_exceeded", extra={"rule": rule.name, "identity": identity})
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
        return response

    def _match(self, request: Request) -> RateLimitRule | None:
        path = request.url.path
        for rule in self.rules:
            if request.method in rule.methods and rule.path_pattern.match(path):
                return rule
        return None
