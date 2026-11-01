"""
Shared API dependencies and tenant isolation helpers for FastAPI v1 endpoints.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.repository import Repository
from app.repositories.repository_repository import RepositoryRepository


def get_request_user_id(request: Request) -> UUID:
    """Extract authenticated user ID from request state."""
    try:
        user_id_val = getattr(request.state, "user_id", None)
        if not user_id_val:
            raise ValueError("user_id not present in request state")
        return UUID(str(user_id_val))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def get_owned_repository(
    repository_id: UUID,
    request: Request,
    db: Session,
    repo_cls: Any = None,
) -> Repository:
    """
    Ensure the repository exists and belongs to the authenticated user.
    Enforces strict tenant isolation across all endpoints.
    """
    if repo_cls is None:
        repo_cls = RepositoryRepository
    user_id = get_request_user_id(request)
    repository = repo_cls(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository


# Aliases for backward compatibility
_request_user_id = get_request_user_id
_owned_repository = get_owned_repository

