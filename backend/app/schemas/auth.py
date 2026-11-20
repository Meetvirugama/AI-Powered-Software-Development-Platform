"""Request and response models for the authentication API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    login: str
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    role: str = "developer"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUser


class UpdateUserRoleRequest(BaseModel):
    role: Literal["viewer", "developer", "admin"]

    @field_validator("role", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserListResponse(BaseModel):
    items: list[AuthenticatedUser]
    total: int
    page: int
    page_size: int
