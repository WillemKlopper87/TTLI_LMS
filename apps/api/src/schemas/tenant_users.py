"""Staff administration shapes (`docs/BACKLOG.md` P3).

Emails are returned in full, deliberately, and unlike the operations
dashboard which masks them — see `services/tenant_users.py`'s module
docstring for why the two screens differ.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RoleSummary(BaseModel):
    """A role and what it actually confers. The permission list is what
    lets the admin screen explain a choice instead of showing a code."""

    code: str
    name: str
    permissions: list[str]


class RolesResponse(BaseModel):
    roles: list[RoleSummary]


class TenantUserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    status: str
    is_guest: bool
    roles: list[str]
    created_at: datetime


class TenantUsersResponse(BaseModel):
    items: list[TenantUserRow]


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)
    # Optional: an account can be created first and given a role later,
    # which is what happens when someone is invited before their job is
    # decided.
    roles: list[str] = Field(default_factory=list)


class RoleChangeRequest(BaseModel):
    role_code: str = Field(min_length=1, max_length=48)


class StatusChangeRequest(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")


__all__ = [
    "InviteUserRequest",
    "RoleChangeRequest",
    "RoleSummary",
    "RolesResponse",
    "StatusChangeRequest",
    "TenantUserRow",
    "TenantUsersResponse",
]
