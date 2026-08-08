from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - the scheme name, not a secret
    expires_in: int


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    tenant_slug: str
    email: str
    permissions: list[str]


__all__ = ["LoginRequest", "MeResponse", "TokenResponse"]
