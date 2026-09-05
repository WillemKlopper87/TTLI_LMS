"""Single sign-on shapes (`docs/BACKLOG.md` P4, gap #46)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.schemas.auth import TokenResponse


class SsoAvailableResponse(BaseModel):
    """What an anonymous login page may know. Deliberately not the
    issuer, the client id or the allowed domains — "does this company
    use SSO" is a fair question for a login page to ask, "what is their
    identity infrastructure" is not."""

    available: bool
    display_name: str | None


class SsoStartResponse(BaseModel):
    """`binding` is for the BFF tier, not for page JavaScript: it parks
    it in an HttpOnly cookie and returns it on the callback, which is
    what stops an attacker's half-finished login being completed in
    somebody else's browser. See `services/oidc.py`'s `begin`."""

    authorization_url: str
    binding: str


class SsoConfigRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    issuer: str = Field(min_length=8, max_length=300)
    client_id: str = Field(min_length=1, max_length=200)
    # Write-only, and optional on update: an admin changing the allowed
    # domains should not have to re-enter the secret, and re-sending it
    # in every PUT would mean the browser holds it in form state.
    client_secret: str | None = Field(default=None, max_length=500)
    allowed_email_domains: list[str] = Field(min_length=1)
    group_role_map: dict[str, str] = Field(default_factory=dict)
    default_role_code: str | None = Field(default=None, max_length=48)
    enabled: bool = False


class SsoConfigResponse(BaseModel):
    """Never carries the client secret — not even masked. A field that
    can only be written is clearer than one that returns asterisks."""

    configured: bool
    protocol: str | None = None
    display_name: str | None = None
    issuer: str | None = None
    client_id: str | None = None
    allowed_email_domains: list[str] = Field(default_factory=list)
    group_role_map: dict[str, str] = Field(default_factory=dict)
    default_role_code: str | None = None
    enabled: bool = False


class SsoCallbackResponse(TokenResponse):
    """A session, plus where the browser should land.

    The deep link a user followed before being sent to their IdP is
    parked with the rest of the flow state; without it on the way back
    out, every SSO login would dump the user on the default screen
    regardless of what they had clicked. `services/oidc.py` is what makes
    sure the value is a path on this site and not somewhere else.
    """

    next_path: str


__all__ = [
    "SsoAvailableResponse",
    "SsoCallbackResponse",
    "SsoConfigRequest",
    "SsoConfigResponse",
    "SsoStartResponse",
]
