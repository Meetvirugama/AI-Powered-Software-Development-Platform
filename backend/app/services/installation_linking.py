"""Single, verified code path for linking a GitHub App installation to a platform user.

Before this module existed, four endpoints linked installations with four different
rules — two of them trusted the ``installation_id`` query parameter blindly, which let
any signed-in user claim somebody else's installation (and therefore read their
private repositories). Every caller now goes through :func:`link_installation_for_user`.

Ownership rule: the installation's GitHub account must be the user's own GitHub
account (matched by numeric account id, falling back to login). Organisation
installations therefore cannot be self-linked; an admin must link them explicitly.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.core.errors import APIError, ErrorCode
from app.models.github_installation import GitHubInstallation
from app.repositories.github_installation_repository import GitHubInstallationRepository

logger = logging.getLogger(__name__)

_INSTALLATION_ID_RE = re.compile(r"^[0-9]{1,20}$")
GITHUB_API_BASE = "https://api.github.com"


def normalize_installation_id(raw: object) -> str:
    """Return a clean numeric installation id or raise 400."""
    value = str(raw or "").strip()
    if not _INSTALLATION_ID_RE.fullmatch(value):
        raise APIError(400, ErrorCode.BAD_REQUEST, "installation_id must be a numeric GitHub installation id.")
    return value


def installation_belongs_to_user(inst_data: dict[str, Any], user: Any) -> bool:
    account = inst_data.get("account") or {}
    account_id = str(account.get("id") or inst_data.get("target_id") or "")
    account_login = str(account.get("login") or "")
    user_github_id = str(getattr(user, "github_id", "") or "")
    user_login = str(getattr(user, "login", "") or "")
    if user_github_id and account_id:
        # Numeric ids never change; logins can be renamed and re-registered by someone else.
        return account_id == user_github_id
    return bool(account_login) and account_login.lower() == user_login.lower()


async def fetch_installation(github_service: Any, installation_id: str) -> dict[str, Any] | None:
    """Fetch installation metadata as the GitHub App. Returns None on 404."""
    try:
        headers = github_service._app_auth_headers()
    except Exception as exc:  # token manager not configured
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub App is not configured.", retryable=True) from exc
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{GITHUB_API_BASE}/app/installations/{installation_id}", headers=headers)
    except httpx.HTTPError as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub is unavailable.", retryable=True) from exc
    if resp.status_code == 404:
        return None
    if not resp.is_success:
        raise APIError(502, ErrorCode.GITHUB_API_ERROR, "Unable to verify GitHub installation.", retryable=True)
    data = resp.json()
    return data if isinstance(data, dict) else None


async def link_installation_for_user(
    db: Any,
    user: Any,
    installation_id: object,
    github_service: Any,
) -> GitHubInstallation:
    """Verify with GitHub that ``user`` owns the installation, then persist the link.

    Raises APIError (400/403/404/503) when the installation cannot be linked.
    Idempotent: re-linking an installation the user already owns is a no-op refresh.
    """
    clean_id = normalize_installation_id(installation_id)
    repo = GitHubInstallationRepository(db)
    existing = repo.get_by_installation_id(clean_id)
    if existing is not None and existing.user_id != user.id:
        logger.warning(
            "installation_link_cross_tenant_blocked",
            extra={"user_id": str(user.id), "installation_id": clean_id},
        )
        raise APIError(403, ErrorCode.FORBIDDEN, "This GitHub installation is linked to another user account.")

    if github_service is None:
        if existing is not None:
            return existing
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub App is not configured; cannot verify installation.")

    inst_data = await fetch_installation(github_service, clean_id)
    if inst_data is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "GitHub installation was not found for this GitHub App.")
    if not installation_belongs_to_user(inst_data, user):
        logger.warning(
            "installation_link_owner_mismatch",
            extra={"user_id": str(user.id), "installation_id": clean_id},
        )
        raise APIError(403, ErrorCode.FORBIDDEN, "GitHub installation account does not match the authenticated user.")

    account_login = str((inst_data.get("account") or {}).get("login") or user.login)
    permissions = inst_data.get("permissions") or {}
    return repo.upsert(
        user_id=user.id,
        installation_id=clean_id,
        account_login=account_login,
        permissions=permissions if isinstance(permissions, dict) else {},
        allow_reassign=False,
    )


async def sync_user_installations(db: Any, user: Any, github_service: Any) -> list[GitHubInstallation]:
    """Discover installations of this App on the user's own account and link them."""
    repo = GitHubInstallationRepository(db)
    if github_service is None:
        return repo.list_by_user(user.id)
    try:
        headers = github_service._app_auth_headers()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{GITHUB_API_BASE}/app/installations?per_page=100", headers=headers)
        if resp.is_success:
            for inst in resp.json() or []:
                if not isinstance(inst, dict) or not installation_belongs_to_user(inst, user):
                    continue
                inst_id = str(inst.get("id") or "")
                existing = repo.get_by_installation_id(inst_id)
                if existing is not None and existing.user_id != user.id:
                    continue
                permissions = inst.get("permissions") or {}
                repo.upsert(
                    user_id=user.id,
                    installation_id=inst_id,
                    account_login=str((inst.get("account") or {}).get("login") or user.login),
                    permissions=permissions if isinstance(permissions, dict) else {},
                    allow_reassign=False,
                )
    except Exception as exc:
        logger.warning("auto_sync_installations_error", extra={"error": str(exc)})
    return repo.list_by_user(user.id)
