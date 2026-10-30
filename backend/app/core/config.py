"""Centralized, environment-driven application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Frozen at module load time — avoids allocating a new set on every validator call.
_ALLOWED_CHAT_PROVIDERS: frozenset[str] = frozenset({"gemini", "groq"})
_ALLOWED_EMBEDDING_PROVIDERS: frozenset[str] = frozenset({"gemini"})


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

    database_url: str = "postgresql+psycopg://platform:platform@localhost:5433/agent_platform"
    redis_url: str = "redis://localhost:6379/0"

    # PostgreSQL connection pool settings for concurrent analysis workloads (Week 2 Section 12 Item 17, B-14)
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Per-feature context token budget defaults (Week 2 Section 12 Item 17, B-14)
    context_budget_explain: int = 4000
    context_budget_bugs: int = 6000
    context_budget_tests: int = 6000
    context_budget_review: int = 8000

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
    cookie_samesite: str | None = None

    # --- AI / LLM Configuration (Gemini Primary, Groq Fallback) -----------
    ai_primary_provider: str = "gemini"
    ai_fallback_provider: str | None = "groq"
    gemini_api_key: str | None = None
    gemini_api_keys: str | None = None     # comma-separated list
    gemini_chat_model: str = "gemini-flash-lite-latest"
    groq_api_key: str | None = None
    groq_api_keys: str | None = None       # comma-separated list
    groq_chat_model: str = "openai/gpt-oss-120b"
    ai_embedding_provider: str = "gemini"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    ai_request_timeout_seconds: float = 30.0
    ai_max_retries: int = 3
    ai_max_output_tokens: int = 2048

    @model_validator(mode="before")
    @classmethod
    def fallback_github_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("github_app_private_key"):
                for alt in ("github_private_key", "GITHUB_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY"):
                    if data.get(alt):
                        data["github_app_private_key"] = data[alt]
                        break
        return data

    @field_validator("ai_primary_provider", "ai_fallback_provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v.lower() not in _ALLOWED_CHAT_PROVIDERS:
            raise ValueError(
                f"Provider '{v}' is not supported. Allowed runtime providers are: {sorted(_ALLOWED_CHAT_PROVIDERS)}. "
                "OpenAI is explicitly prohibited."
            )
        return v.lower()

    @field_validator("ai_embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, v: str) -> str:
        if v.lower() not in _ALLOWED_EMBEDDING_PROVIDERS:
            raise ValueError(
                f"Embedding provider '{v}' is not supported. Required runtime provider is: 'gemini'. "
                "OpenAI is explicitly prohibited."
            )
        return v.lower()

    @property
    def all_gemini_keys(self) -> list[str]:
        keys = []
        if self.gemini_api_key:
            keys.append(self.gemini_api_key.strip())
        if self.gemini_api_keys:
            keys.extend([k.strip() for k in self.gemini_api_keys.split(",") if k.strip()])
        # Deduplicate preserving order
        return list(dict.fromkeys(keys))

    @property
    def all_groq_keys(self) -> list[str]:
        keys = []
        if self.groq_api_key:
            keys.append(self.groq_api_key.strip())
        if self.groq_api_keys:
            keys.extend([k.strip() for k in self.groq_api_keys.split(",") if k.strip()])
        return list(dict.fromkeys(keys))

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

    @property
    def effective_cookie_samesite(self) -> str:
        if self.cookie_samesite:
            return self.cookie_samesite.lower()
        return "none" if self.cookie_secure else "lax"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Fail closed on insecure production defaults (F-04)."""
        is_prod = self.app_env.lower() in ("production", "prod")
        if is_prod:
            if not self.jwt_secret or len(self.jwt_secret.strip()) < 32:
                raise ValueError(
                    "Production configuration error: JWT_SECRET must be configured with at least 32 characters."
                )
            insecure_dummies = {"test-secret", "dev-secret", "changeme", "placeholder"}
            if any(dummy in self.jwt_secret.lower() for dummy in insecure_dummies) or self.jwt_secret.lower().strip() == "secret":
                raise ValueError(
                    "Production configuration error: Insecure default JWT_SECRET detected in production."
                )
            if not self.cookie_secure:
                raise ValueError(
                    "Production configuration error: COOKIE_SECURE must be True in production."
                )
            for origin in self.cors_origins:
                if "localhost" in origin or "127.0.0.1" in origin:
                    raise ValueError(
                        f"Production configuration error: Localhost CORS origin '{origin}' is not permitted in production."
                    )
            if not self.cors_origins:
                raise ValueError(
                    "Production configuration error: CORS_ALLOWED_ORIGINS must contain valid production origins."
                )
            if self.jwt_expire_minutes > 1440:
                raise ValueError(
                    "Production configuration error: JWT_EXPIRE_MINUTES must not exceed 1440 minutes in production."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance per process."""
    return Settings()
