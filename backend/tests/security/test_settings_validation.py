"""Security and configuration validation tests (TST-01, TST-05, TST-28).

Validates:
- Rejection of committed JWT placeholder secrets and low-entropy secrets.
- Requirement for anchored CORS regex in production.
- Prohibition of enable_dev_login in production.
- Validation of cookie samesite defaults.
"""

import pytest
from app.core.config import Settings

PROD_KWARGS = {
    "app_env": "production",
    "cookie_secure": True,
    "cors_allowed_origins": "https://app.example.com",
    "frontend_url": "https://app.example.com",
    "cors_origin_regex": r"^https://[a-zA-Z0-9-]+\.example\.com$",
}


def test_production_rejects_committed_jwt_placeholders():
    """TST-01: In production, committed dummy secrets must be rejected."""
    dummy_secrets = [
        "production-deployment-minimum-32-chars-secret-key-ok",
        "generate-a-strong-32-character-secret-key-here-for-production",
        "test-secret-that-has-over-thirty-two-characters-long",
        "dev-secret-that-has-over-thirty-two-characters-long",
        "changeme-changeme-changeme-changeme-changeme",
        "placeholder-secret-placeholder-secret-placeholder",
        "example-secret-key-that-is-thirty-two-characters",
        "your-secret-key-here-must-be-very-long-and-secure",
        "sample-secret-key-for-local-testing-purposes-only",
    ]
    for dummy in dummy_secrets:
        with pytest.raises(ValueError, match="(Insecure default or placeholder JWT_SECRET|lacks sufficient entropy)"):
            Settings(
                jwt_secret=dummy,
                **PROD_KWARGS,
            )


def test_production_rejects_low_entropy_jwt_secret():
    """TST-01: JWT secret with fewer than 12 distinct characters must be rejected."""
    low_entropy = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 1 distinct char, 32 len
    with pytest.raises(ValueError, match="lacks sufficient entropy"):
        Settings(
            jwt_secret=low_entropy,
            **PROD_KWARGS,
        )

    low_entropy_repeated = "abcabcabcabcabcabcabcabcabcabcab"  # 3 distinct chars
    with pytest.raises(ValueError, match="lacks sufficient entropy"):
        Settings(
            jwt_secret=low_entropy_repeated,
            **PROD_KWARGS,
        )


def test_production_rejects_short_jwt_secret():
    """TST-01: JWT secret under 32 characters in production must be rejected."""
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(
            jwt_secret="short-secret-key",
            **PROD_KWARGS,
        )


def test_production_accepts_strong_high_entropy_secret():
    """TST-01: A high-entropy 32+ char secret in production must succeed."""
    strong_secret = "k9#mP$2vL!xQ8wZ@4rT&7yU*1oI^6eB%"  # >32 len, 25+ unique chars
    s = Settings(
        jwt_secret=strong_secret,
        **PROD_KWARGS,
    )
    assert s.jwt_secret == strong_secret
    assert s.is_production is True


def test_production_rejects_enable_dev_login():
    """TST-28: Dev login must never be enabled in production."""
    with pytest.raises(ValueError, match="ENABLE_DEV_LOGIN cannot be enabled in production"):
        Settings(
            jwt_secret="k9#mP$2vL!xQ8wZ@4rT&7yU*1oI^6eB%",
            enable_dev_login=True,
            **PROD_KWARGS,
        )


def test_production_enforces_anchored_cors_regex():
    """TST-05: CORS origin regex in production must be anchored with ^ and $."""
    base_kwargs = {
        "app_env": "production",
        "cookie_secure": True,
        "cors_allowed_origins": "https://app.example.com",
        "frontend_url": "https://app.example.com",
        "jwt_secret": "k9#mP$2vL!xQ8wZ@4rT&7yU*1oI^6eB%",
    }
    # Unanchored prefix
    with pytest.raises(ValueError, match=r"strictly anchored with \^ and \$"):
        Settings(
            cors_origin_regex=r"https://[a-zA-Z0-9-]+\.example\.com$",
            **base_kwargs,
        )

    # Unanchored suffix
    with pytest.raises(ValueError, match=r"strictly anchored with \^ and \$"):
        Settings(
            cors_origin_regex=r"^https://[a-zA-Z0-9-]+\.example\.com",
            **base_kwargs,
        )


def test_cookie_samesite_default_is_lax():
    """TST-28: Default cookie SameSite policy must be 'lax', not 'none'."""
    s = Settings(cookie_samesite="")
    assert s.effective_cookie_samesite == "lax"

    s_explicit = Settings(cookie_samesite="strict")
    assert s_explicit.effective_cookie_samesite == "strict"
