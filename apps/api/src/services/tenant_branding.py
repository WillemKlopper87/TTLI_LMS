"""Tenant branding and custom domains (`docs/BACKLOG.md` P3, feature-
matrix gaps #44 and #45).

White-label theming has *worked* since `0006` — two demo tenants prove
it at runtime — but only a migration could change a colour or a logo,
and only a migration could add a hostname. That is the gap: the
capability was built and then left without a door.

**Contrast is validated, not trusted.** A tenant setting its own brand
colour can trivially produce white-on-yellow buttons, and this platform
holds a WCAG 2.1 AA line that an axe gate now enforces on every public
page. So `primary_color` is checked against the on-brand text colour it
will carry and refused below 4.5:1 rather than accepted and rendered
illegibly. The tenant is told the measured ratio, not just "invalid".

**Domain verification is deliberately not self-attested.** Adding a
hostname is what routes traffic to a tenant, so letting an admin mark
their own domain verified would make "verified" mean nothing. A domain
is stored unverified with the DNS TXT value its owner must publish;
proving it — an actual resolver lookup — is Phase 7 work alongside TLS
automation, and `tls_status` stays `pending` until then rather than
claiming a state nobody checked. The token is derived by HMAC from the
tenant and hostname rather than stored, so it is stable, unguessable
without the server secret, and needs no column.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.models.tenant import TenantDomain
from src.models.theme import TenantTheme

HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
# Any hostname a browser can reach: labels of alphanumerics and hyphens,
# at least one dot. Deliberately not a full RFC parser — the check exists
# to refuse obvious rubbish before it reaches a unique index.
HOSTNAME = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

MIN_CONTRAST = 4.5


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(one: str, two: str) -> float:
    """WCAG 2.1's own formula, the same one `globals.css` documents its
    computed ratios from — not an approximation."""
    a, b = relative_luminance(one), relative_luminance(two)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def assert_readable(colour: str, *, against: str, field: str) -> None:
    if not HEX_COLOUR.match(colour):
        raise AppError("Colours must be a six-digit hex value like #8e151c.", {"field": field})
    ratio = contrast_ratio(colour, against)
    if ratio < MIN_CONTRAST:
        raise AppError(
            "That colour is not readable enough to use as a brand colour — "
            f"it measures {ratio:.1f}:1 against the text that sits on it, and "
            f"WCAG AA needs {MIN_CONTRAST}:1.",
            {"field": field, "contrast": round(ratio, 2), "required": MIN_CONTRAST},
        )


async def get_theme(session: AsyncSession, *, tenant_id: uuid.UUID) -> TenantTheme | None:
    return (
        await session.execute(select(TenantTheme).where(TenantTheme.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def upsert_theme(
    session: AsyncSession, *, tenant_id: uuid.UUID, changes: dict[str, str | None]
) -> TenantTheme:
    """A tenant may never have had a theme row — `0006` seeded only the
    demo tenants — so this creates one rather than 404ing on a tenant
    that simply never customised anything."""
    theme = await get_theme(session, tenant_id=tenant_id)
    if theme is None:
        theme = TenantTheme(tenant_id=tenant_id)
        session.add(theme)
    for field, value in changes.items():
        setattr(theme, field, value)
    await session.flush()
    return theme


def verification_token(*, secret: str, tenant_id: uuid.UUID, hostname: str) -> str:
    """Derived, not stored: stable for a given (tenant, hostname), and
    unguessable without the server secret, so no column and no rotation
    problem."""
    digest = hmac.new(
        secret.encode(), f"{tenant_id}:{hostname.lower()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"ttli-verify={digest[:32]}"


async def list_domains(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[TenantDomain]:
    return list(
        (
            await session.execute(
                select(TenantDomain)
                .where(TenantDomain.tenant_id == tenant_id)
                .order_by(TenantDomain.is_primary.desc(), TenantDomain.hostname)
            )
        )
        .scalars()
        .all()
    )


async def add_domain(session: AsyncSession, *, tenant_id: uuid.UUID, hostname: str) -> TenantDomain:
    normalised = hostname.strip().lower().rstrip(".")
    if not HOSTNAME.match(normalised):
        raise AppError("That does not look like a hostname.", {"hostname": hostname})

    # Hostnames are globally unique — they are how a request finds its
    # tenant — so a clash is refused rather than silently re-pointed,
    # and the refusal does not say which tenant holds it.
    taken = (
        await session.execute(select(TenantDomain.id).where(TenantDomain.hostname == normalised))
    ).scalar_one_or_none()
    if taken is not None:
        raise AppError("That hostname is already in use.", {"hostname": normalised})

    domain = TenantDomain(tenant_id=tenant_id, hostname=normalised, is_primary=False)
    session.add(domain)
    await session.flush()
    return domain


async def remove_domain(
    session: AsyncSession, *, tenant_id: uuid.UUID, domain_id: uuid.UUID
) -> TenantDomain:
    domain = (
        await session.execute(
            select(TenantDomain).where(
                TenantDomain.id == domain_id, TenantDomain.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if domain is None:
        raise AppError("No such domain.", {"domain_id": str(domain_id)})
    if domain.is_primary:
        # The primary hostname is how everyone reaches this tenant.
        # Removing it through a settings screen would take the tenant off
        # the internet, which is not a thing a settings screen should be
        # able to do.
        raise AppError("The primary hostname cannot be removed — it is how this tenant is reached.")
    await session.delete(domain)
    await session.flush()
    return domain


__all__ = [
    "MIN_CONTRAST",
    "add_domain",
    "assert_readable",
    "contrast_ratio",
    "get_theme",
    "list_domains",
    "relative_luminance",
    "remove_domain",
    "upsert_theme",
    "verification_token",
]
