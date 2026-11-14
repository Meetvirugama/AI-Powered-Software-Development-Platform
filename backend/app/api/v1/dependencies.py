"""
Shared API dependencies, tenant isolation helpers, and Role-Based Access Control (RBAC) guards for FastAPI v1 endpoints (F01 / F30).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.repository import Repository
from app.models.user import UserRole
from app.repositories.repository_repository import RepositoryRepository

ROLE_HIERARCHY: dict[str, int] = {
    UserRole.VIEWER.value: 1,
    UserRole.DEVELOPER.value: 2,
    UserRole.ADMIN.value: 3,
}


def get_request_user_id(request: Request) -> UUID:
    """Extract authenticated user ID from request state."""
    try:
        user_id_val = getattr(request.state, "user_id", None)
        if not user_id_val:
            raise ValueError("user_id not present in request state")
        return UUID(str(user_id_val))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def get_request_user_role(request: Request) -> str:
    """Extract authenticated user's role from request state, defaulting to 'developer'."""
    return getattr(request.state, "role", UserRole.DEVELOPER.value) or UserRole.DEVELOPER.value


def require_role(*allowed_roles: str | UserRole):
    """
    FastAPI dependency factory enforcing Role-Based Access Control (RBAC).
    Raises HTTP 403 Forbidden with ErrorCode.FORBIDDEN if user role is not permitted.
    """
    normalized_allowed = {
        (r.value if isinstance(r, UserRole) else str(r)).lower()
        for r in allowed_roles
    }

    def _dependency(request: Request) -> str:
        current_role = get_request_user_role(request).lower()
        if current_role not in normalized_allowed:
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Insufficient privileges. Role '{current_role}' is not authorized for this resource.",
            )
        return current_role

    return _dependency


def require_min_role(min_role: str | UserRole):
    """
    FastAPI dependency factory enforcing a minimum role in the hierarchy (VIEWER < DEVELOPER < ADMIN).
    """
    min_role_str = (min_role.value if isinstance(min_role, UserRole) else str(min_role)).lower()
    min_level = ROLE_HIERARCHY.get(min_role_str, 2)

    def _dependency(request: Request) -> str:
        current_role = get_request_user_role(request).lower()
        current_level = ROLE_HIERARCHY.get(current_role, 1)
        if current_level < min_level:
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Insufficient privileges. Action requires at least '{min_role_str}' role.",
            )
        return current_role

    return _dependency


def require_permission(permission: str):
    """
    FastAPI dependency factory enforcing granular permission check.
    Admin role automatically possesses all permissions.
    """
    def _dependency(request: Request) -> str:
        current_role = get_request_user_role(request).lower()
        if current_role == UserRole.ADMIN.value:
            return permission
        perms = set(getattr(request.state, "permissions", []))
        if permission not in perms:
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Missing required permission: '{permission}'.",
            )
        return permission

    return _dependency


def get_owned_repository(
    repository_id: UUID,
    request: Request,
    db: Session,
    repo_cls: Any = None,
    min_role: str | UserRole | None = None,
) -> Repository:
    """
    Ensure the repository exists and belongs to the authenticated user.
    Enforces strict tenant isolation and optional minimum RBAC role across all endpoints.
    """
    if repo_cls is None:
        repo_cls = RepositoryRepository
    user_id = get_request_user_id(request)

    if min_role is not None:
        min_role_str = (min_role.value if isinstance(min_role, UserRole) else str(min_role)).lower()
        min_level = ROLE_HIERARCHY.get(min_role_str, 2)
        current_role = get_request_user_role(request).lower()
        current_level = ROLE_HIERARCHY.get(current_role, 1)
        if current_level < min_level:
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Insufficient privileges for repository operations. Requires at least '{min_role_str}' role.",
            )

    repository = repo_cls(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository


def get_owned_task(
    task_id: UUID,
    request: Request,
    db: Session,
    task_repo_cls: Any = None,
    min_role: str | UserRole | None = None,
) -> tuple[Any, UUID]:
    """
    Ensure the task exists and belongs to the authenticated user.
    Enforces strict tenant isolation and optional minimum RBAC role across all task endpoints.
    """
    if min_role is not None:
        min_role_str = (min_role.value if isinstance(min_role, UserRole) else str(min_role)).lower()
        min_level = ROLE_HIERARCHY.get(min_role_str, 2)
        current_role = get_request_user_role(request).lower()
        current_level = ROLE_HIERARCHY.get(current_role, 1)
        if current_level < min_level:
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Insufficient privileges for task operations. Requires at least '{min_role_str}' role.",
            )

    if task_repo_cls is None:
        from app.repositories.task_repository import TaskRepository
        task_repo_cls = TaskRepository
    user_id = get_request_user_id(request)
    task = task_repo_cls(db).get_task(task_id, user_id=user_id)
    if task is None:
        raise APIError(
            404,
            ErrorCode.TASK_NOT_FOUND,
            f"Task '{task_id}' was not found or you do not have access.",
        )
    return task, user_id


# Aliases for backward compatibility
_request_user_id = get_request_user_id
_owned_repository = get_owned_repository
_owned_task = get_owned_task



