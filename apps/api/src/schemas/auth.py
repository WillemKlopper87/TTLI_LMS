from __future__ import annotations

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
    user_id: str
    tenant_id: str
    tenant_slug: str
    email: str
    permissions: list[str]


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
