"""Security Test: Security Headers and CSP (TST-18 / ISS-021 / OPT-12).

Verifies that security headers (nosniff, DENY, Referrer-Policy, Content-Security-Policy, HSTS)
are enforced across the FastAPI backend and Vercel SPA configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app
from fastapi.testclient import TestClient


def test_tst18_api_security_headers_present() -> None:
    """Every HTTP response from the API must include security headers including CSP."""
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_tst18_hsts_header_on_https_request() -> None:
    """HTTPS requests must include Strict-Transport-Security."""
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert "max-age=" in resp.headers.get("Strict-Transport-Security", "")


def test_tst18_spa_vercel_json_security_headers_and_csp() -> None:
    """Vercel configurations for SPA must define security headers and CSP."""
    repo_root = Path(__file__).resolve().parents[3]
    for config_path in [repo_root / "vercel.json", repo_root / "frontend" / "vercel.json"]:
        assert config_path.is_file(), f"{config_path} must exist"
        data = json.loads(config_path.read_text())
        headers_section = data.get("headers", [])
        assert headers_section, f"{config_path} missing headers block"
        headers_map = {h["key"]: h["value"] for item in headers_section for h in item.get("headers", [])}
        assert headers_map.get("X-Content-Type-Options") == "nosniff"
        assert headers_map.get("X-Frame-Options") == "DENY"
        assert headers_map.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        csp = headers_map.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
