"""Centralized, environment-driven application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Agentic Software Engineering Platform"
    app_version: str = "1.0.0"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/agent_platform"
    redis_url: str = "redis://localhost:6379/0"

    github_app_id: str | None = None
    github_app_private_key: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_webhook_secret: str | None = None
    github_workspace_root: str | None = None
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    github_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/github/callback"
    auth_cookie_name: str = "access_token"
    cookie_secure: bool = False

    # --- API security (W1 Day 6) -------------------------------------------
    # Comma-separated list of frontend origins allowed to call the API with
    # cookies. Never use "*" here: browsers reject "*" with credentials, and it
    # would let any website read API responses on a logged-in user's behalf.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_enabled: bool = True
    # Only true when running behind a trusted reverse proxy / load balancer that
    # sets X-Forwarded-For and X-Forwarded-Proto. Otherwise clients could spoof
    # their IP to dodge the per-IP rate limit.
    trust_proxy_headers: bool = False

    @property
    def cors_origins(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_allowed_origins.split(",") if o.strip()]
        return [o for o in origins if o != "*"]


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance per process."""
    return Settings()
