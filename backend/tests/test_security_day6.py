"""
Day 6 — API Security tests.
Owner: Sukun — W1

Covers Docs/week1.md "Day 6 — API Security":
    Rate limiting   auth callback 10/min per IP · sync 5/min per user · chat 30/min per user
    Headers         X-Content-Type-Options, X-Frame-Options, HSTS (HTTPS only)
    CORS            only known frontend origins

Run with:
    pytest backend/tests/test_security_day6.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.core.rate_limit as rate_limit
from app.core.rate_limit import InMemoryRateLimitStore, RedisRateLimitStore
from app.core.security import create_access_token
from app.main import app

ALLOWED_ORIGIN = "http://localhost:5173"
EVIL_ORIGIN = "https://evil.example.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def limiter_store(monkeypatch) -> InMemoryRateLimitStore:
    """Fresh in-memory counters for every test (no Redis needed)."""
    store = InMemoryRateLimitStore()
    monkeypatch.setattr(rate_limit, "get_rate_limit_store", lambda: store)
    return store


def _other_user_headers() -> dict[str, str]:
    token, _ = create_access_token(str(uuid4()))
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. Rate limiting
# ===========================================================================

class TestRateLimiting:
    def test_auth_callback_allows_10_then_429(self, client, limiter_store):
        url = "/api/v1/auth/github/callback?code=abc&state=xyz"
        for i in range(10):
            res = client.get(url)
            assert res.status_code != 429, f"request {i + 1} was rate limited too early"
        res = client.get(url)
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "RATE_LIMITED"
        assert res.json()["error"]["retryable"] is True
        assert 1 <= int(res.headers["Retry-After"]) <= 60

    def test_auth_callback_ignores_spoofed_forwarded_for(self, client, limiter_store):
        """Changing X-Forwarded-For must not reset the per-IP counter (no trusted proxy)."""
        url = "/api/v1/auth/github/callback?code=abc&state=xyz"
        for i in range(10):
            client.get(url, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        res = client.get(url, headers={"X-Forwarded-For": "10.0.0.99"})
        assert res.status_code == 429

    def test_sync_allows_5_per_user_then_429(self, client, auth_headers, limiter_store):
        url = f"/api/v1/repositories/{uuid4()}/sync"
        for i in range(5):
            res = client.post(url, headers=auth_headers)
            assert res.status_code != 429, f"request {i + 1} was rate limited too early"
        res = client.post(url, headers=auth_headers)
        assert res.status_code == 429

    def test_sync_limit_is_per_user_not_global(self, client, auth_headers, limiter_store):
        url = f"/api/v1/repositories/{uuid4()}/sync"
        for _ in range(6):
            client.post(url, headers=auth_headers)
        res = client.post(url, headers=_other_user_headers())
        assert res.status_code != 429

    def test_sync_limit_covers_all_repositories_of_a_user(self, client, auth_headers, limiter_store):
        """Switching repository id must not bypass the per-user limit."""
        for _ in range(5):
            client.post(f"/api/v1/repositories/{uuid4()}/sync", headers=auth_headers)
        res = client.post(f"/api/v1/repositories/{uuid4()}/sync", headers=auth_headers)
        assert res.status_code == 429

    def test_chat_allows_30_per_user_then_429(self, client, auth_headers, limiter_store):
        url = f"/api/v1/repositories/{uuid4()}/chat"
        body = {"question": "Where is auth?"}
        for i in range(30):
            res = client.post(url, json=body, headers=auth_headers)
            assert res.status_code != 429, f"request {i + 1} was rate limited too early"
        res = client.post(url, json=body, headers=auth_headers)
        assert res.status_code == 429

    def test_rate_limit_headers_present(self, client, auth_headers, limiter_store):
        res = client.post(f"/api/v1/repositories/{uuid4()}/sync", headers=auth_headers)
        assert res.headers["X-RateLimit-Limit"] == "5"
        assert res.headers["X-RateLimit-Remaining"] == "4"

    def test_unlimited_routes_are_not_counted(self, client, auth_headers, limiter_store):
        for _ in range(50):
            assert client.get("/api/v1/repositories", headers=auth_headers).status_code != 429
        assert limiter_store.counts == {}

    def test_limiter_fails_open_when_redis_is_down(self, client, auth_headers, monkeypatch):
        class BrokenStore:
            def hit(self, key, window_seconds):
                raise ConnectionError("redis down")

        monkeypatch.setattr(rate_limit, "get_rate_limit_store", lambda: BrokenStore())
        for _ in range(10):
            res = client.post(f"/api/v1/repositories/{uuid4()}/sync", headers=auth_headers)
            assert res.status_code != 429


def test_redis_store_uses_incr_and_expire():
    calls = []

    class FakePipeline:
        def incr(self, key):
            calls.append(("incr", key))

        def expire(self, key, seconds):
            calls.append(("expire", key, seconds))

        def execute(self):
            return [3, True]

    class FakeRedis:
        def pipeline(self):
            return FakePipeline()

    assert RedisRateLimitStore(FakeRedis()).hit("ratelimit:k", 60) == 3
    assert calls[0] == ("incr", "ratelimit:k")
    assert calls[1][0] == "expire" and calls[1][2] >= 60


# ===========================================================================
# 2. Security headers
# ===========================================================================

class TestSecurityHeaders:
    def test_headers_on_normal_response(self, client):
        res = client.get("/health")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"

    def test_no_hsts_over_plain_http(self, client):
        res = client.get("/health")
        assert "Strict-Transport-Security" not in res.headers

    def test_hsts_over_https(self):
        with TestClient(app, base_url="https://testserver") as https_client:
            res = https_client.get("/health")
        assert "max-age=" in res.headers["Strict-Transport-Security"]

    def test_headers_on_401_from_auth_middleware(self, client):
        res = client.get("/api/v1/repositories")
        assert res.status_code == 401
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"

    def test_headers_on_429(self, client, auth_headers, limiter_store):
        url = f"/api/v1/repositories/{uuid4()}/sync"
        for _ in range(5):
            client.post(url, headers=auth_headers)
        res = client.post(url, headers=auth_headers)
        assert res.status_code == 429
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"

    def test_headers_on_unknown_path(self, client):
        res = client.get("/does-not-exist")
        assert res.headers["X-Content-Type-Options"] == "nosniff"


# ===========================================================================
# 3. CORS
# ===========================================================================

def _preflight(client, origin: str):
    return client.options(
        "/api/v1/repositories",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )


class TestCORS:
    def test_preflight_from_frontend_allowed(self, client):
        res = _preflight(client, ALLOWED_ORIGIN)
        assert res.status_code == 200
        assert res.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
        assert res.headers["Access-Control-Allow-Credentials"] == "true"

    def test_preflight_does_not_need_a_token(self, client):
        """Browsers never send cookies on OPTIONS; JWT must not block the preflight."""
        assert _preflight(client, ALLOWED_ORIGIN).status_code != 401

    def test_preflight_from_unknown_origin_rejected(self, client):
        res = _preflight(client, EVIL_ORIGIN)
        assert res.headers.get("Access-Control-Allow-Origin") != EVIL_ORIGIN
        assert res.status_code >= 400

    def test_simple_request_from_unknown_origin_gets_no_cors_header(self, client):
        res = client.get("/health", headers={"Origin": EVIL_ORIGIN})
        assert "Access-Control-Allow-Origin" not in res.headers

    def test_never_wildcard_origin(self, client):
        res = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
        assert res.headers.get("Access-Control-Allow-Origin") == ALLOWED_ORIGIN
        assert res.headers.get("Access-Control-Allow-Origin") != "*"

    def test_cors_setting_drops_wildcard(self):
        from app.core.config import Settings
        s = Settings(cors_allowed_origins="*, http://localhost:5173/")
        assert s.cors_origins == ["http://localhost:5173"]
