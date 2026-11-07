"""Comprehensive security test suite for Issue #181 Batch 1.

Covers:
1. Platform JWT security (PyJWT migration, claims contract, algorithm allowlist, tampering, malformed claims).
2. JWT Revocation fail-closed behavior (Redis availability, timeout, error, expiration TTL).
3. GitHub OAuth state security (single-use, atomic consumption, PKCE S256, CSRF binding, fail-closed Redis).
4. Redirect validation and CSRF cookie protections (open redirect prevention, Origin verification, SameSite/Secure).
5. Dual trust-domain isolation (Platform HS256 vs. GitHub App RS256).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import (
    ALLOWED_PLATFORM_ALGORITHMS,
    TOKEN_TYPE_ACCESS,
    create_access_token,
    decode_access_token,
)
from app.integrations.github.client import GitHubClient
from app.integrations.github.token_manager import InstallationTokenManager
from app.main import app
from app.models.user import User


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_rsa_key_pair() -> tuple[str, str]:
    """Generate a test RSA 2048-bit keypair for RS256 GitHub App signing tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pem_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return pem_private, pem_public


class MemoryRedis:
    """Thread-safe, atomic-compliant Redis in-memory test double."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl_store: dict[str, int] = {}
        self.blocklisted: set[str] = set()

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, *args: Any, **kwargs: Any) -> bool:
        self.store[key] = str(value)
        return True

    def setex(self, key: str, time_sec: int, value: str) -> bool:
        self.store[key] = str(value)
        self.ttl_store[key] = time_sec
        if key.startswith("auth:blocklist:"):
            self.blocklisted.add(key)
        return True

    def exists(self, key: str) -> int:
        return int(key in self.store or key in self.blocklisted)

    def delete(self, key: str) -> int:
        existed = key in self.store or key in self.blocklisted
        self.store.pop(key, None)
        self.ttl_store.pop(key, None)
        self.blocklisted.discard(key)
        return int(existed)

    def getdel(self, key: str) -> str | None:
        val = self.store.pop(key, None)
        self.ttl_store.pop(key, None)
        self.blocklisted.discard(key)
        return val

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        if numkeys >= 1 and keys_and_args:
            key = keys_and_args[0]
            val = self.store.pop(key, None)
            self.ttl_store.pop(key, None)
            self.blocklisted.discard(key)
            return val
        return None

    def ping(self) -> bool:
        return True


def _configure_test_settings(monkeypatch, **overrides: Any) -> Settings:
    defaults = {
        "jwt_secret": "test-secret-at-least-32-chars-long-security-gate",
        "jwt_algorithm": "HS256",
        "jwt_expire_minutes": 15,
        "jwt_issuer": "agent-platform",
        "jwt_audience": "agent-platform-web",
        "github_client_id": "test-github-client-id",
        "github_client_secret": "test-github-client-secret",
        "cors_allowed_origins": "http://localhost:5173,http://127.0.0.1:5173",
        "frontend_url": "http://localhost:5173",
        "cookie_secure": False,
        "rate_limit_enabled": False,
        "app_env": "development",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k.upper(), str(v))
    get_settings.cache_clear()
    return get_settings()


# ===========================================================================
# 1. Platform JWT Tests
# ===========================================================================

class TestPlatformJWT:
    """Test suite for hardened platform JWT issuance and validation."""

    def test_valid_access_jwt(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        user_id = str(uuid.uuid4())
        token, expires_in = create_access_token(user_id)

        assert isinstance(token, str)
        assert expires_in == 15 * 60

        claims = decode_access_token(token)
        assert claims["sub"] == user_id
        assert isinstance(claims["jti"], str) and len(claims["jti"]) > 10
        assert claims["iss"] == "agent-platform"
        assert claims["aud"] == "agent-platform-web"
        assert claims["token_type"] == TOKEN_TYPE_ACCESS
        assert claims["type"] == TOKEN_TYPE_ACCESS
        assert claims["exp"] > claims["iat"]

    def test_invalid_signature_rejected(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        user_id = str(uuid.uuid4())
        token, _ = create_access_token(user_id)

        # Decode with a different secret
        with pytest.raises(jwt.exceptions.InvalidSignatureError):
            jwt.decode(token, "wrong-secret-32-bytes-long-padding-xyz", algorithms=["HS256"], audience="agent-platform-web")
        # Ensure our decode_access_token catches signature mismatch
        monkeypatch.setenv("JWT_SECRET", "completely-different-signing-secret-32b")
        get_settings.cache_clear()
        with pytest.raises(APIError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_expired_jwt_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        user_id = str(uuid.uuid4())
        now = int(time.time())
        expired_payload = {
            "sub": user_id,
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now - 3600,
            "exp": now - 1800,  # Expired 30 minutes ago
        }
        expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")

        with pytest.raises(APIError) as exc_info:
            decode_access_token(expired_token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.message.lower()

    def test_invalid_algorithm_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        user_id = str(uuid.uuid4())
        now = int(time.time())
        payload = {
            "sub": user_id,
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        # Token crafted with 'none' algorithm
        none_token = jwt.encode(payload, key="", algorithm="none")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(none_token)
        assert exc_info.value.status_code == 401

    def test_missing_subject_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        payload = {
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_missing_jti_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        payload = {
            "sub": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_missing_or_wrong_issuer_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        # Missing issuer
        p1 = {
            "sub": str(uuid.uuid4()),
            "jti": str(uuid.uuid4()),
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        t1 = jwt.encode(p1, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t1)
        assert exc_info.value.status_code == 401

        # Wrong issuer
        p2 = dict(p1, iss="rogue-identity-provider")
        t2 = jwt.encode(p2, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t2)
        assert exc_info.value.status_code == 401

    def test_missing_or_wrong_audience_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        # Missing audience
        p1 = {
            "sub": str(uuid.uuid4()),
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        t1 = jwt.encode(p1, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t1)
        assert exc_info.value.status_code == 401

        # Wrong audience
        p2 = dict(p1, aud="unintended-service")
        t2 = jwt.encode(p2, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t2)
        assert exc_info.value.status_code == 401

    def test_missing_issued_at_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        payload = {
            "sub": str(uuid.uuid4()),
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "exp": now + 900,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_invalid_token_type_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        payload = {
            "sub": str(uuid.uuid4()),
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": "refresh_token",  # Refresh token passed where access token required
            "iat": now,
            "exp": now + 900,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_malformed_claim_values_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        # Empty string subject
        p1 = {
            "sub": "   ",
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": now + 900,
        }
        t1 = jwt.encode(p1, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError):
            decode_access_token(t1)

        # exp <= iat
        p2 = dict(p1, sub="valid-user", exp=now - 10)
        t2 = jwt.encode(p2, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError):
            decode_access_token(t2)

    def test_invalid_token_format_rejected(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        for invalid_raw in ["", "   ", "not-a-token", "foo.bar", "a.b.c.d"]:
            with pytest.raises(APIError) as exc_info:
                decode_access_token(invalid_raw)
            assert exc_info.value.status_code == 401

    def test_missing_issuer_or_audience_config_fails(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch, jwt_issuer="")
        with pytest.raises(APIError) as exc_info:
            create_access_token(str(uuid.uuid4()))
        assert exc_info.value.status_code == 500

        with pytest.raises(APIError) as exc_info2:
            decode_access_token("some.dummy.token")
        assert exc_info2.value.status_code == 500

    def test_non_positive_expire_minutes_fails(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch, jwt_expire_minutes=0)
        with pytest.raises(APIError) as exc_info:
            create_access_token(str(uuid.uuid4()))
        assert exc_info.value.status_code == 500

    def test_boolean_claims_rejected(self, monkeypatch) -> None:
        settings = _configure_test_settings(monkeypatch)
        now = int(time.time())
        # sub as boolean
        p1 = {
            "sub": True,
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "token_type": "access",
            "iat": now,
            "exp": now + 600,
        }
        t1 = jwt.encode(p1, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t1)
        assert exc_info.value.status_code == 401

        # jti as boolean
        p2 = dict(p1, sub="valid-user", jti=True)
        t2 = jwt.encode(p2, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t2)
        assert exc_info.value.status_code == 401

        # exp as boolean
        p3 = dict(p1, sub="valid-user", exp=True)
        t3 = jwt.encode(p3, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(APIError) as exc_info:
            decode_access_token(t3)
        assert exc_info.value.status_code == 401


# ===========================================================================
# 2. Redis Revocation & Fail-Closed Tests
# ===========================================================================

class TestRevocationAndFailClosed:
    """Test suite for Redis-backed revocation fail-closed resilience."""

    def test_valid_unrevoked_token_succeeds(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        token, _ = create_access_token(str(uuid.uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_revoked_token_returns_401(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)

        token, _ = create_access_token(str(uuid.uuid4()))
        claims = decode_access_token(token)
        fake_redis.blocklisted.add(f"auth:blocklist:{claims['jti']}")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert "revoked" in response.json()["error"]["message"]

    def test_redis_connection_error_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        token, _ = create_access_token(str(uuid.uuid4()))

        class BrokenRedis:
            def exists(self, key: str) -> int:
                raise ConnectionError("Connection refused to Redis cluster")

        monkeypatch.setattr("app.core.auth.get_redis", lambda: BrokenRedis())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_redis_timeout_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        token, _ = create_access_token(str(uuid.uuid4()))

        class TimingOutRedis:
            async def exists(self, key: str) -> int:
                await asyncio.sleep(3.0)  # Exceeds the 1.5s timeout
                return 0

        monkeypatch.setattr("app.core.auth.get_redis", lambda: TimingOutRedis())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_missing_redis_client_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        token, _ = create_access_token(str(uuid.uuid4()))

        # Redis returns None
        monkeypatch.setattr("app.core.auth.get_redis", lambda: None)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_logout_sets_correct_ttl_on_blocklist(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        token, _ = create_access_token(str(uuid.uuid4()))
        claims = decode_access_token(token)
        jti = claims["jti"]

        client = TestClient(app, raise_server_exceptions=False)
        res = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 204

        block_key = f"auth:blocklist:{jti}"
        assert block_key in fake_redis.store
        ttl = fake_redis.ttl_store.get(block_key, 0)
        # Token had 15 minutes lifetime; TTL should be near 900 seconds
        assert 800 <= ttl <= 900

    def test_redis_py_timeout_error_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        token, _ = create_access_token(str(uuid.uuid4()))

        from redis.exceptions import TimeoutError as RedisTimeout

        class RedisSocketTimeout:
            def exists(self, key: str) -> int:
                raise RedisTimeout("Redis socket read timed out")

        monkeypatch.setattr("app.core.auth.get_redis", lambda: RedisSocketTimeout())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_logout_fails_closed_when_redis_client_none(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: None)

        token, _ = create_access_token(str(uuid.uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        res = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


# ===========================================================================
# 3. GitHub OAuth State & PKCE Tests
# ===========================================================================

class TestGitHubOAuthStateAndPKCE:
    """Test suite for OAuth CSRF state binding, PKCE S256, and atomic consumption."""

    def test_oauth_login_generates_random_state_and_pkce_challenge(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/auth/github/login", follow_redirects=False)

        assert response.status_code == 307
        loc = response.headers["location"]
        assert "client_id=" in loc
        assert "state=" in loc
        assert "code_challenge=" in loc
        assert "code_challenge_method=S256" in loc

        # Verify state cookie set
        assert "oauth_state=" in response.headers["set-cookie"]
        cookie_header = response.headers["set-cookie"]
        assert "HttpOnly" in cookie_header or "httponly" in cookie_header.lower()

        # Extract state from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(loc)
        qs = urllib.parse.parse_qs(parsed.query)
        state_param = qs["state"][0]
        challenge_param = qs["code_challenge"][0]

        # Verify persisted verifier in Redis
        verifier_stored = fake_redis.get(f"oauth_state:{state_param}")
        assert verifier_stored is not None
        # Verify challenge matches SHA-256 of verifier
        expected_digest = hashlib.sha256(verifier_stored.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).decode("ascii").rstrip("=")
        assert challenge_param == expected_challenge

    def test_oauth_login_fails_closed_when_redis_unavailable(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)

        class BrokenRedis:
            def setex(self, *args, **kwargs):
                raise ConnectionError("Redis is offline")

        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: BrokenRedis())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/auth/github/login", follow_redirects=False)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        # No redirect and no cookie issued
        assert "set-cookie" not in response.headers or "oauth_state" not in response.headers.get("set-cookie", "")
        assert response.headers.get("location") is None

    def test_oauth_callback_atomic_consumption_and_replay_rejection(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "test-atomic-state-12345"
        verifier = "test-verifier-64-characters-random-string-high-entropy-security"
        fake_redis.setex(f"oauth_state:{state}", 600, verifier)

        async def _mock_profile(code: str, code_verifier: str | None = None):
            assert code == "gh-code-99"
            assert code_verifier == verifier
            return {"id": 123456, "login": "oauth_user", "email": "oauth@example.com", "avatar_url": None}

        monkeypatch.setattr("app.api.v1.auth._github_user_for_code", _mock_profile)

        class FakeUserRepo:
            def __init__(self, session: Any) -> None:
                pass

            def upsert_github_user(self, *args: Any, **kwargs: Any) -> Any:
                u = User(login="oauth_user", github_id=123456)
                u.id = uuid.uuid4()
                return u

        monkeypatch.setattr("app.api.v1.auth.UserRepository", FakeUserRepo)
        app.dependency_overrides[get_db] = lambda: object()

        try:
            client = TestClient(app, raise_server_exceptions=False)
            client.cookies.set("oauth_state", state)

            # First callback call: succeeds and consumes state
            resp1 = client.get(
                f"/api/v1/auth/github/callback?code=gh-code-99&state={state}",
                follow_redirects=False,
            )
            assert resp1.status_code == 302
            # State must now be gone from Redis
            assert fake_redis.get(f"oauth_state:{state}") is None

            # Replay attempt: must be rejected with 400 OAUTH_STATE_INVALID
            client.cookies.set("oauth_state", state)
            resp2 = client.get(
                f"/api/v1/auth/github/callback?code=gh-code-99&state={state}",
                follow_redirects=False,
            )
            assert resp2.status_code == 400
            assert resp2.json()["error"]["code"] == "OAUTH_STATE_INVALID"
        finally:
            app.dependency_overrides.clear()

    def test_oauth_callback_mismatched_cookie_rejects(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "state-in-redis"
        fake_redis.setex(f"oauth_state:{state}", 600, "verifier")

        client = TestClient(app, raise_server_exceptions=False)
        # Attacker state in query, victim state in cookie
        client.cookies.set("oauth_state", "victim-cookie-state")
        resp = client.get(
            f"/api/v1/auth/github/callback?code=code123&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "OAUTH_STATE_INVALID"
        # State in redis must NOT have been consumed by attacker's failed attempt
        assert fake_redis.get(f"oauth_state:{state}") is not None

    def test_oauth_callback_redis_outage_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)

        class ErrorRedis:
            def getdel(self, key: str):
                raise ConnectionError("Redis server crashed")

            def eval(self, *args, **kwargs):
                raise ConnectionError("Redis server crashed")

        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: ErrorRedis())

        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set("oauth_state", "some-state")
        resp = client.get(
            "/api/v1/auth/github/callback?code=code123&state=some-state",
            follow_redirects=False,
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_oauth_callback_missing_state_cookie_rejects(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "state-without-cookie"
        fake_redis.setex(f"oauth_state:{state}", 600, "test-verifier")

        client = TestClient(app, raise_server_exceptions=False)
        # No cookie provided
        resp = client.get(
            f"/api/v1/auth/github/callback?code=gh-code&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "OAUTH_STATE_INVALID"
        # State in redis must not be consumed
        assert fake_redis.get(f"oauth_state:{state}") is not None
        # Must instruct client to clear cookie
        set_cookie = resp.headers.get("set-cookie", "")
        assert "oauth_state" in set_cookie

    def test_oauth_callback_expired_or_missing_redis_state_rejects(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "expired-state"
        # State NOT in redis

        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set("oauth_state", state)
        resp = client.get(
            f"/api/v1/auth/github/callback?code=gh-code&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "OAUTH_STATE_INVALID"
        set_cookie = resp.headers.get("set-cookie", "")
        assert "oauth_state" in set_cookie

    def test_oauth_callback_concurrent_replay_race_condition(self, monkeypatch) -> None:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        _configure_test_settings(monkeypatch)

        class ThreadSafeRedis(MemoryRedis):
            def __init__(self) -> None:
                super().__init__()
                self._lock = threading.Lock()

            def getdel(self, key: str) -> str | None:
                with self._lock:
                    return super().getdel(key)

            def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
                with self._lock:
                    return super().eval(script, numkeys, *keys_and_args)

        thread_redis = ThreadSafeRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: thread_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: thread_redis)

        state = "concurrent-race-state"
        verifier = "concurrent-verifier-64-characters-random-string-high-entropy-val"
        thread_redis.setex(f"oauth_state:{state}", 600, verifier)

        async def _mock_profile(code: str, code_verifier: str | None = None):
            return {"id": 888123, "login": "concurrent_user", "email": "conc@example.com", "avatar_url": None}

        monkeypatch.setattr("app.api.v1.auth._github_user_for_code", _mock_profile)

        class FakeUserRepo:
            def __init__(self, session: Any) -> None:
                pass

            def upsert_github_user(self, *args: Any, **kwargs: Any) -> Any:
                u = User(login="concurrent_user", github_id=888123)
                u.id = uuid.uuid4()
                return u

        monkeypatch.setattr("app.api.v1.auth.UserRepository", FakeUserRepo)
        app.dependency_overrides[get_db] = lambda: object()

        try:
            client = TestClient(app, raise_server_exceptions=False)
            client.cookies.set("oauth_state", state)

            def run_callback() -> int:
                r = client.get(
                    f"/api/v1/auth/github/callback?code=gh-code-race&state={state}",
                    follow_redirects=False,
                )
                return r.status_code

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(run_callback) for _ in range(8)]
                status_codes = [f.result() for f in futures]

            # Exactly one request must succeed with 302, and all other 7 must be rejected with 400
            assert status_codes.count(302) == 1
            assert status_codes.count(400) == 7
            assert thread_redis.get(f"oauth_state:{state}") is None
        finally:
            app.dependency_overrides.clear()

    def test_oauth_callback_redis_timeout_fails_closed_503(self, monkeypatch) -> None:
        _configure_test_settings(monkeypatch)
        from redis.exceptions import TimeoutError as RedisTimeout

        class TimeoutRedis:
            def getdel(self, key: str):
                raise RedisTimeout("Timeout while executing GETDEL")

        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: TimeoutRedis())

        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set("oauth_state", "some-state")
        resp = client.get(
            "/api/v1/auth/github/callback?code=code123&state=some-state",
            follow_redirects=False,
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "oauth_state" in resp.headers.get("set-cookie", "")

    def test_consume_oauth_state_decodes_bytes_properly(self) -> None:
        from app.api.v1.auth import _consume_oauth_state

        class BytesRedis:
            def getdel(self, key: str):
                return b"raw_bytes_verifier_token_abc"

        res = _consume_oauth_state(BytesRedis(), "test_state")
        assert res == "raw_bytes_verifier_token_abc"
        assert not res.startswith("b'")

    def test_consume_oauth_state_fails_closed_without_atomic_support(self) -> None:
        from app.api.v1.auth import _consume_oauth_state

        class NonAtomicRedis:
            def get(self, key: str):
                return "verifier"

            def delete(self, key: str):
                return 1

        with pytest.raises(ConnectionError) as exc_info:
            _consume_oauth_state(NonAtomicRedis(), "test_state")
        assert "atomic" in str(exc_info.value).lower()


# ===========================================================================
# 4. Redirect Validation & CSRF Cookie Protection Tests
# ===========================================================================

class TestRedirectAndCSRFProtection:
    """Test suite for open-redirect prevention and cookie CSRF checks."""

    def test_allowed_frontend_redirect(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            cors_allowed_origins="https://app.example.com",
            frontend_url="https://app.example.com",
        )
        from app.api.v1.auth import _resolve_trusted_frontend_url

        url = _resolve_trusted_frontend_url("https://app.example.com/dashboard")
        assert url == "https://app.example.com/dashboard"

        # Relative path
        url_rel = _resolve_trusted_frontend_url("/dashboard")
        assert url_rel.startswith("https://app.example.com")

    def test_rejected_arbitrary_redirect_prevents_open_redirect(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            cors_allowed_origins="https://app.example.com",
            frontend_url="https://app.example.com",
        )
        from app.api.v1.auth import _resolve_trusted_frontend_url

        # Untrusted external origins
        for attack_url in [
            "https://evil.com/phish",
            "http://attacker.org",
            "//evil.com",
            "javascript:alert(1)",
        ]:
            safe_url = _resolve_trusted_frontend_url(attack_url)
            assert "evil.com" not in safe_url
            assert "attacker.org" not in safe_url
            assert safe_url.startswith("https://app.example.com")

    def test_csrf_cookie_authenticated_mutation_requires_valid_origin(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            cors_allowed_origins="http://localhost:5173",
        )
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        token, _ = create_access_token(str(uuid.uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(settings.auth_cookie_name, token)

        # 1. Untrusted origin on state-changing request -> rejected 403
        resp_untrusted = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://malicious-website.com"},
        )
        assert resp_untrusted.status_code == 403
        assert resp_untrusted.json()["error"]["code"] == "FORBIDDEN"

        # 2. Trusted origin on state-changing request -> accepted
        resp_trusted = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp_trusted.status_code == 204

    def test_production_missing_origin_and_referer_rejected_403(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            app_env="production",
            cookie_secure=True,
            jwt_secret="prod-super-secure-crypto-key-999-abcdefg-1234567890",
            cors_allowed_origins="https://my-prod-frontend.com",
            frontend_url="https://my-prod-frontend.com",
        )
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        token, _ = create_access_token(str(uuid.uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(settings.auth_cookie_name, token)

        # In production, cookie mutation without Origin or Referer header must be rejected
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_oauth_callback_query_redirect_url_allowed_destination(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            cors_allowed_origins="https://app.example.com",
            frontend_url="https://app.example.com",
        )
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "redir-test-state"
        verifier = "redir-verifier-64-characters-random-string-high-entropy-val"
        fake_redis.setex(f"oauth_state:{state}", 600, verifier)

        async def _mock_profile(code: str, code_verifier: str | None = None):
            return {"id": 112233, "login": "redir_user", "email": "redir@example.com", "avatar_url": None}

        monkeypatch.setattr("app.api.v1.auth._github_user_for_code", _mock_profile)

        class FakeUserRepo:
            def __init__(self, session: Any) -> None:
                pass

            def upsert_github_user(self, *args: Any, **kwargs: Any) -> Any:
                u = User(login="redir_user", github_id=112233)
                u.id = uuid.uuid4()
                return u

        monkeypatch.setattr("app.api.v1.auth.UserRepository", FakeUserRepo)
        app.dependency_overrides[get_db] = lambda: object()

        try:
            client = TestClient(app, raise_server_exceptions=False)
            client.cookies.set("oauth_state", state)

            resp = client.get(
                f"/api/v1/auth/github/callback?code=gh-code&state={state}&redirect_url=https://app.example.com/custom-page",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "https://app.example.com/custom-page"
        finally:
            app.dependency_overrides.clear()

    def test_oauth_callback_query_redirect_url_attack_destination_blocked(self, monkeypatch) -> None:
        settings = _configure_test_settings(
            monkeypatch,
            cors_allowed_origins="https://app.example.com",
            frontend_url="https://app.example.com",
        )
        fake_redis = MemoryRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)

        state = "attack-redir-test-state"
        verifier = "attack-verifier-64-characters-random-string-high-entropy-val"
        fake_redis.setex(f"oauth_state:{state}", 600, verifier)

        async def _mock_profile(code: str, code_verifier: str | None = None):
            return {"id": 112234, "login": "redir_user2", "email": "redir2@example.com", "avatar_url": None}

        monkeypatch.setattr("app.api.v1.auth._github_user_for_code", _mock_profile)

        class FakeUserRepo:
            def __init__(self, session: Any) -> None:
                pass

            def upsert_github_user(self, *args: Any, **kwargs: Any) -> Any:
                u = User(login="redir_user2", github_id=112234)
                u.id = uuid.uuid4()
                return u

        monkeypatch.setattr("app.api.v1.auth.UserRepository", FakeUserRepo)
        app.dependency_overrides[get_db] = lambda: object()

        try:
            client = TestClient(app, raise_server_exceptions=False)
            client.cookies.set("oauth_state", state)

            resp = client.get(
                f"/api/v1/auth/github/callback?code=gh-code&state={state}&redirect_url=https://evil-phish.com/login",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            # Open redirect blocked: redirected to safe frontend base
            assert "evil-phish.com" not in resp.headers["location"]
            assert resp.headers["location"].startswith("https://app.example.com")
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 5. Dual Trust-Domain Separation (Platform HS256 vs GitHub App RS256)
# ===========================================================================

class TestDualTrustDomainIsolation:
    """Test suite ensuring platform HS256 and GitHub App RS256 remain strictly decoupled."""

    def test_github_app_rs256_token_generation(self, test_rsa_key_pair, monkeypatch) -> None:
        pem_private, pem_public = test_rsa_key_pair
        app_id = "987654"

        settings = Settings(
            app_env="development",
            github_app_id=app_id,
            github_app_private_key=pem_private,
            jwt_secret="platform-secret-never-used-for-github-app-tokens-32b",
        )
        mock_redis = MagicMock()
        manager = InstallationTokenManager(mock_redis, settings)

        app_jwt = manager._build_app_jwt()
        assert isinstance(app_jwt, str)

        # Verify decoding with RSA public key using PyJWT
        decoded = jwt.decode(app_jwt, pem_public, algorithms=["RS256"])
        assert decoded["iss"] == app_id
        assert decoded["exp"] > decoded["iat"]
        assert decoded["exp"] - decoded["iat"] == 660  # 60s past skew + 600s TTL

    def test_platform_token_cannot_decode_with_rsa_key(self, test_rsa_key_pair, monkeypatch) -> None:
        pem_private, pem_public = test_rsa_key_pair
        _configure_test_settings(monkeypatch)

        token, _ = create_access_token(str(uuid.uuid4()))

        # Attempting to decode platform HS256 token with RSA public key must fail
        with pytest.raises(jwt.PyJWTError):
            jwt.decode(token, pem_public, algorithms=["RS256"])

    def test_github_app_jwt_rejected_by_platform_token_decoder(self, test_rsa_key_pair, monkeypatch) -> None:
        pem_private, _ = test_rsa_key_pair
        _configure_test_settings(monkeypatch)

        now = int(time.time())
        app_payload = {
            "iss": "987654",
            "iat": now - 60,
            "exp": now + 600,
        }
        app_jwt = jwt.encode(app_payload, pem_private, algorithm="RS256")

        # Platform decoder only allows HS256 and checks platform claims
        with pytest.raises(APIError) as exc_info:
            decode_access_token(app_jwt)
        assert exc_info.value.status_code == 401
