from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - the scheme name, not a secret
    expires_in: int


class MfaChallengeResponse(BaseModel):
    """Returned with 202 in place of TokenResponse when MFA is required."""

    mfa_required: bool = True
    mfa_token: str


class MeResponse(BaseModel):
    """The signed-in shell's whole identity payload: who the caller is,
    what they may do, and — for a guest — how long they still have.
    `full_name`/`first_name` are null for the many accounts checkout and
    guest flows never captured a name for; `initials` never is (see
    services/identity.py::display_identity)."""

    user_id: str
    tenant_id: str
    tenant_slug: str
    email: str
    permissions: list[str]
    full_name: str | None = None
    first_name: str | None = None
    initials: str
    is_guest: bool = False
    guest_expires_at: datetime | None = None
    guest_days_left: int | None = None


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkConsumeRequest(BaseModel):
    token: str = Field(min_length=1)


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    # A 6-digit TOTP code or an XXXXX-XXXXX recovery code.
    code: str = Field(min_length=6, max_length=16)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class MfaEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str
    enrollment_token: str


class MfaEnrollConfirmRequest(BaseModel):
    enrollment_token: str
    code: str = Field(min_length=6, max_length=6)


class MfaEnrollConfirmResponse(BaseModel):
    recovery_codes: list[str]


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1)
    # Minimum length is the one composition rule worth having; the real
    # defence is Argon2id plus rate limiting (04 §1.1, §1.4).
    new_password: str = Field(min_length=12, max_length=256)


__all__ = [
    "LoginRequest",
    "LogoutRequest",
    "MagicLinkConsumeRequest",
    "MagicLinkRequest",
    "MeResponse",
    "MfaChallengeResponse",
    "MfaEnrollConfirmRequest",
    "MfaEnrollConfirmResponse",
    "MfaEnrollResponse",
    "MfaVerifyRequest",
    "PasswordResetConfirmRequest",
    "PasswordResetRequest",
    "RefreshRequest",
    "TokenResponse",
]
