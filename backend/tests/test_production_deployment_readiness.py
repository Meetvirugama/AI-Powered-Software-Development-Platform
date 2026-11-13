"""Production deployment configuration, startup, Vercel, and endpoint readiness tests."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.core.config import Settings
from app.core.database import normalize_sync_database_url
from app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDatabaseAndRedisProductionHardening:
    """Verify Supabase SSL/pooler URL normalization and Upstash/Azure Redis TLS guards."""

    def test_supabase_url_enforces_sslmode_when_missing(self) -> None:
        raw = "postgres://postgres.proj:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        normalized = normalize_sync_database_url(raw)
        assert normalized.startswith("postgresql+psycopg://")
        assert "sslmode=require" in normalized

    def test_supabase_url_preserves_existing_sslmode(self) -> None:
        raw = "postgresql://postgres.proj:pw@db.proj.supabase.co:5432/postgres?sslmode=verify-full"
        normalized = normalize_sync_database_url(raw)
        assert normalized.startswith("postgresql+psycopg://")
        assert normalized.count("sslmode=") == 1
        assert "sslmode=verify-full" in normalized

    @pytest.mark.parametrize(
        "bad_redis_url",
        [
            "redis://default:token@my-cache.upstash.io:6379",
            "redis://:key@my-cache.redis.cache.windows.net:6379/0",
        ],
    )
    def test_cloud_redis_requires_tls_in_production(self, bad_redis_url: str) -> None:
        with pytest.raises(ValidationError, match="rediss://"):
            Settings(
                _env_file=None,
                app_env="production",
                jwt_secret="a" * 32,
                cookie_secure=True,
                cors_allowed_origins="https://app.example.com",
                redis_url=bad_redis_url,
            )

    def test_upstash_rediss_and_docker_compose_redis_permitted(self) -> None:
        prod_upstash = Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="a" * 32,
            cookie_secure=True,
            cors_allowed_origins="https://app.example.com",
            redis_url="rediss://default:token@my-cache.upstash.io:6379",
        )
        assert prod_upstash.redis_url.startswith("rediss://")

        prod_compose = Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="a" * 32,
            cookie_secure=True,
            cors_allowed_origins="https://app.example.com",
            redis_url="redis://redis:6379/0",
        )
        assert prod_compose.redis_url == "redis://redis:6379/0"

    def test_wildcard_cors_origin_regex_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="CORS_ORIGIN_REGEX"):
            Settings(
                _env_file=None,
                app_env="production",
                jwt_secret="a" * 32,
                cookie_secure=True,
                cors_allowed_origins="https://app.example.com",
                cors_origin_regex=".*",
            )


class TestDeploymentConfigsAndStartupScript:
    """Verify Azure startup.sh, Vercel rewrites/headers, and env template parity."""

    def test_startup_script_port_migrations_and_proxy_guards(self) -> None:
        raw_bytes = (REPO_ROOT / "startup.sh").read_bytes()
        assert b"\r\n" not in raw_bytes
        startup = raw_bytes.decode("utf-8")
        assert "${WEBSITES_PORT:-${PORT:-8000}}" in startup
        assert "RUN_MIGRATIONS_ON_STARTUP" in startup
        assert "TRUST_PROXY_HEADERS" in startup
        assert "--timeout-graceful-shutdown" in startup

    def test_vercel_configs_rewrites_and_security_headers(self) -> None:
        root_vercel = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
        frontend_vercel = json.loads((REPO_ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))

        assert "npm ci && npm run build" in root_vercel["buildCommand"]
        assert root_vercel["outputDirectory"] == "frontend/dist"

        for cfg in (root_vercel, frontend_vercel):
            rewrites = cfg["rewrites"]
            assert any(r["source"] == "/api/:path*" and r["destination"].startswith("https://") for r in rewrites)
            assert any(r["source"] == "/(.*)" and r["destination"] == "/index.html" for r in rewrites)
            header_keys = {h["key"] for rule in cfg["headers"] for h in rule["headers"]}
            assert {"X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"} <= header_keys

    def test_env_templates_contain_required_production_keys(self) -> None:
        prod_env = (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8")
        dev_env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        for key in (
            "APP_ENV=production",
            "DATABASE_URL=",
            "REDIS_URL=rediss://",
            "JWT_ISSUER=",
            "JWT_AUDIENCE=",
            "COOKIE_SECURE=true",
            "COOKIE_SAMESITE=none",
            "TRUST_PROXY_HEADERS=true",
            "DISABLE_EMBEDDED_SYNC_WORKER=true",
            "RUN_MIGRATIONS_ON_STARTUP=true",
        ):
            assert key in prod_env, f"Missing '{key}' in .env.production.example"

        for key in ("DATABASE_URL=", "REDIS_URL=", "JWT_ISSUER=", "JWT_AUDIENCE=", "COOKIE_SAMESITE="):
            assert key in dev_env, f"Missing '{key}' in .env.example"


class TestBackendHealthAndDocsEndpoints:
    """Verify health, readiness, and Swagger endpoints respond via ASGI TestClient."""

    def test_health_and_docs_endpoints_respond(self) -> None:
        client = TestClient(app)
        health_res = client.get("/api/v1/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "ok"
        assert health_res.headers.get("X-Content-Type-Options") == "nosniff"
        assert health_res.headers.get("X-Frame-Options") == "DENY"

        docs_res = client.get("/docs")
        assert docs_res.status_code == 200

        ready_res = client.get("/api/v1/health/ready")
        assert ready_res.status_code in (200, 503)
        ready_body = ready_res.json()
        assert {"status", "database", "redis", "llm_gateway", "rag_pipeline"} <= set(ready_body.keys())
