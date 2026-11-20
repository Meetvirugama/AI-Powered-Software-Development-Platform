"""Regression tests for the Module 1 (Authentication & User Management) audit fixes.

Covers:
- Refresh tokens are single-use (rotation + reuse detection, with a short multi-tab grace window).
- Logout revokes the refresh token as well as the access token.
- GitHub App installations can no longer be linked without ownership verification.
- Role management endpoints (admin only, last-admin protection).
- Viewer role is blocked from write operations.
- Admin bootstrap via ADMIN_GITHUB_LOGINS and exact (non-wildcard) login lookup.
"""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.models.github_installation import GitHubInstallation
from app.models.user import User
from app.repositories.user_repository import UserRepository


def _make_user(db_session, *, login: str, role: str = "developer", github_id: str | None = None) -> User:
    user = User(id=uuid4(), github_id=github_id or f"gh-{uuid4().hex[:10]}", login=login, role=role)
    db_session.add(user)
    db_session.commit()
    return user


def _bearer(user: User, role: str | None = None) -> dict[str, str]:
    token, _ = create_access_token(str(user.id), role=role or user.role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Refresh rotation / reuse detection
# ---------------------------------------------------------------------------

def test_refresh_token_reuse_after_grace_window_is_rejected(client: TestClient, db_session, fake_redis) -> None:
    user = _make_user(db_session, login=f"rot_{uuid4().hex[:6]}")
    refresh_tok, _ = create_refresh_token(user.id)
    jti = decode_refresh_token(refresh_tok)["jti"]
    settings = get_settings()

    client.cookies.set(settings.refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200

    # Pretend the first use happened a minute ago (outside the multi-tab grace window).
    fake_redis.store[f"auth:refresh_revoked:{jti}"] = f"{time.time() - 60:.3f}"
    client.cookies.clear()
    client.cookies.set(settings.refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "UNAUTHORIZED"


def test_refresh_with_non_uuid_subject_returns_401_not_500(client: TestClient) -> None:
    refresh_tok, _ = create_refresh_token("not-a-uuid")
    client.cookies.set(get_settings().refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_access_token_is_not_accepted_as_refresh_token(client: TestClient, db_session) -> None:
    user = _make_user(db_session, login=f"acc_{uuid4().hex[:6]}")
    resp = client.post("/api/v1/auth/refresh", headers=_bearer(user))
    assert resp.status_code == 401


def test_logout_revokes_refresh_cookie(client: TestClient, db_session, fake_redis) -> None:
    user = _make_user(db_session, login=f"out_{uuid4().hex[:6]}")
    refresh_tok, _ = create_refresh_token(user.id)
    jti = decode_refresh_token(refresh_tok)["jti"]
    settings = get_settings()

    client.cookies.set(settings.refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    out = client.post("/api/v1/auth/logout", headers=_bearer(user))
    assert out.status_code == 204
    assert fake_redis.store.get(f"auth:refresh_revoked:{jti}") == "revoked"

    client.cookies.set(settings.refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    after = client.post("/api/v1/auth/refresh")
    assert after.status_code == 401


# ---------------------------------------------------------------------------
# GitHub App installation linking
# ---------------------------------------------------------------------------

def test_link_installation_requires_github_verification(client: TestClient, db_session, monkeypatch) -> None:
    """Previously any user could claim any installation id; now it must be verified with GitHub."""
    user = _make_user(db_session, login=f"lnk_{uuid4().hex[:6]}")
    # GitHub App not configured -> ownership cannot be verified -> must not link
    monkeypatch.setattr(client.app.state, "github_service", None, raising=False)
    resp = client.post(
        "/api/v1/github/installations/link",
        json={"installation_id": "123456789"},
        headers=_bearer(user),
    )
    assert resp.status_code == 503
    assert db_session.query(GitHubInstallation).filter_by(installation_id="123456789").first() is None


def test_link_installation_rejects_non_numeric_id(client: TestClient, db_session) -> None:
    user = _make_user(db_session, login=f"bad_{uuid4().hex[:6]}")
    resp = client.post(
        "/api/v1/github/installations/link",
        json={"installation_id": "../../evil"},
        headers=_bearer(user),
    )
    assert resp.status_code == 400


def test_installation_callback_does_not_link_unverified_installation(
    client: TestClient, db_session, monkeypatch
) -> None:
    attacker = _make_user(db_session, login=f"atk_{uuid4().hex[:6]}")
    token, _ = create_access_token(str(attacker.id))
    monkeypatch.setattr(client.app.state, "github_service", None, raising=False)
    client.cookies.set(get_settings().auth_cookie_name, token)
    resp = client.get(
        "/api/v1/github/installation/callback?installation_id=987654321&setup_action=install",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "installation_id=987654321" in resp.headers["location"]
    assert db_session.query(GitHubInstallation).filter_by(installation_id="987654321").first() is None


def test_viewer_cannot_link_installation(client: TestClient, db_session) -> None:
    viewer = _make_user(db_session, login=f"vw_{uuid4().hex[:6]}", role="viewer")
    resp = client.post(
        "/api/v1/github/installations/link",
        json={"installation_id": "111"},
        headers=_bearer(viewer),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Role management
# ---------------------------------------------------------------------------

def test_non_admin_cannot_list_or_change_roles(client: TestClient, db_session) -> None:
    dev = _make_user(db_session, login=f"dev_{uuid4().hex[:6]}")
    assert client.get("/api/v1/auth/users", headers=_bearer(dev)).status_code == 403
    resp = client.patch(f"/api/v1/auth/users/{dev.id}/role", json={"role": "admin"}, headers=_bearer(dev))
    assert resp.status_code == 403


def test_admin_can_assign_roles(client: TestClient, db_session) -> None:
    admin = _make_user(db_session, login=f"adm_{uuid4().hex[:6]}", role="admin")
    target = _make_user(db_session, login=f"tgt_{uuid4().hex[:6]}")

    resp = client.patch(f"/api/v1/auth/users/{target.id}/role", json={"role": "viewer"}, headers=_bearer(admin))
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"

    bad = client.patch(f"/api/v1/auth/users/{target.id}/role", json={"role": "superuser"}, headers=_bearer(admin))
    assert bad.status_code in (400, 422)

    listing = client.get("/api/v1/auth/users?role=viewer", headers=_bearer(admin))
    assert listing.status_code == 200
    assert any(item["id"] == str(target.id) for item in listing.json()["items"])


def test_last_admin_cannot_be_demoted(client: TestClient, db_session) -> None:
    for existing in db_session.query(User).filter(User.role == "admin").all():
        existing.role = "developer"
    db_session.commit()
    admin = _make_user(db_session, login=f"solo_{uuid4().hex[:6]}", role="admin")
    resp = client.patch(f"/api/v1/auth/users/{admin.id}/role", json={"role": "developer"}, headers=_bearer(admin))
    assert resp.status_code == 409


def test_unknown_role_claim_is_treated_as_viewer(client: TestClient, db_session) -> None:
    user = _make_user(db_session, login=f"unk_{uuid4().hex[:6]}")
    resp = client.post(
        "/api/v1/github/installations/link",
        json={"installation_id": "222"},
        headers=_bearer(user, role="superadmin"),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User repository
# ---------------------------------------------------------------------------

def test_admin_bootstrap_promotes_listed_login(db_session) -> None:
    repo = UserRepository(db_session)
    login = f"boot_{uuid4().hex[:6]}"
    user = repo.upsert_github_user(f"gh-{uuid4().hex[:8]}", login, admin_logins=frozenset({login.lower()}))
    assert user.role == "admin"


def test_upsert_keeps_existing_email_when_github_hides_it(db_session) -> None:
    repo = UserRepository(db_session)
    gh_id = f"gh-{uuid4().hex[:8]}"
    login = f"mail_{uuid4().hex[:6]}"
    repo.upsert_github_user(gh_id, login, "kept@example.com")
    again = repo.upsert_github_user(gh_id, login, None)
    assert again.email == "kept@example.com"


def test_get_by_login_does_not_treat_underscore_as_wildcard(db_session) -> None:
    suffix = uuid4().hex[:6]
    _make_user(db_session, login=f"abc{suffix}")
    repo = UserRepository(db_session)
    assert repo.get_by_login(f"a_c{suffix}") is None
    assert repo.get_by_login(f"ABC{suffix}") is not None
