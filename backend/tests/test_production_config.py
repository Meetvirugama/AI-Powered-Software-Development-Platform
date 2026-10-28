"""Tests for production security configuration defaults and validation (F-04, F-15)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_dev_settings_permissive() -> None:
    """In development, defaults allow local testing without HTTPS or production secrets."""
    dev_settings = Settings(
        _env_file=None,
        app_env="development",
        jwt_secret="short",
        cookie_secure=False,
        cors_allowed_origins="http://localhost:5173",
    )
    assert dev_settings.app_env == "development"
    assert dev_settings.cookie_secure is False
    assert dev_settings.jwt_expire_minutes == 15
    assert dev_settings.gemini_chat_model == "gemini-flash-lite-latest"


def test_prod_settings_fail_closed_missing_secret() -> None:
    """Production mode must reject missing or weak JWT secret."""
    with pytest.raises(ValidationError, match="JWT_SECRET must be configured with at least 32 characters"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="too-short",
            cookie_secure=True,
            cors_allowed_origins="https://app.example.com",
        )


def test_prod_settings_fail_closed_dummy_secret() -> None:
    """Production mode must reject well-known test secrets even if long."""
    with pytest.raises(ValidationError, match="Insecure default JWT_SECRET detected"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="test-secret-test-secret-test-secret-32",
            cookie_secure=True,
            cors_allowed_origins="https://app.example.com",
        )


def test_prod_settings_fail_closed_insecure_cookie() -> None:
    """Production mode must require secure cookies."""
    with pytest.raises(ValidationError, match="COOKIE_SECURE must be True in production"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="a" * 32,
            cookie_secure=False,
            cors_allowed_origins="https://app.example.com",
        )


def test_prod_settings_fail_closed_localhost_cors() -> None:
    """Production mode must reject localhost CORS origins."""
    with pytest.raises(ValidationError, match="Localhost CORS origin"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="a" * 32,
            cookie_secure=True,
            cors_allowed_origins="http://localhost:5173",
        )


def test_prod_settings_valid() -> None:
    """Production mode succeeds with proper production settings."""
    prod = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="super-secure-production-jwt-secret-key-32-chars",
        cookie_secure=True,
        cors_allowed_origins="https://app.example.com,https://dashboard.example.com",
        jwt_expire_minutes=60,
    )
    assert prod.app_env == "production"
    assert prod.cookie_secure is True
    assert prod.cors_origins == ["https://app.example.com", "https://dashboard.example.com"]
