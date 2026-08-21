"""Tenant branding and custom domains (`docs/BACKLOG.md` P3, feature-
matrix gaps #44 and #45) — the half of tenant self-service that staff
administration left open.

White-label theming has worked since `0006` and custom hostnames since
`0001`; neither could be changed without a migration. `tenant:manage`
gates both, because a brand colour and a hostname are tenant
configuration in exactly the sense that permission names.

Reads are separate from the public `GET /tenant/theme`, which stays
unauthenticated because the login page needs it before anyone has a
session. This one returns the editable record, including fields that
public route deliberately never exposes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile, status

from src.core.deps import (
    AuditedSessionDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    TenantDep,
)
from src.core.errors import AppError, ServiceUnavailable
from src.models.audit import AuditAction
from src.models.tenant import TenantDomain
from src.models.theme import TenantTheme
from src.schemas.tenant_branding import (
    AddDomainRequest,
    BrandingResponse,
    BrandingUpdateRequest,
    DomainRow,
    DomainsResponse,
)
from src.services import antivirus, audit
from src.services import tenant_branding as branding
from src.services.storage.base import Container

router = APIRouter(prefix="/tenant", tags=["tenant"])

MANAGE = "tenant:manage"

# The colour a tenant picks carries this text; contrast is measured
# against it rather than against a guess. Matches --on-brand in
# globals.css, which is what actually renders on a brand-coloured button.
ON_BRAND = "#fdf8f9"

# SVG is deliberately absent. It is a script-carrying format served from
# a public container, and "an administrator uploaded it" is not a reason
# to host active content — raster logos do the job. Flagged by a security
# review of this file on 2026-08-21.
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
LOGO_MAX_BYTES = 2 * 1024 * 1024


def _branding(theme: TenantTheme | None) -> BrandingResponse:
    return BrandingResponse(
        logo_url=getattr(theme, "logo_url", None),
        primary_color=getattr(theme, "primary_color", None),
        secondary_color=getattr(theme, "secondary_color", None),
        login_background_url=getattr(theme, "login_background_url", None),
        support_email=getattr(theme, "support_email", None),
        email_footer_text=getattr(theme, "email_footer_text", None),
    )


@router.get(
    "/branding",
    response_model=BrandingResponse,
    summary="The editable branding record for this tenant",
)
async def get_branding(principal: PrincipalDep, session: SessionDep) -> BrandingResponse:
    principal.require(MANAGE)
    return _branding(await branding.get_theme(session, tenant_id=principal.tenant_id))


@router.patch(
    "/branding",
    response_model=BrandingResponse,
    summary="Change colours, support address and email footer",
)
async def update_branding(
    body: BrandingUpdateRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> BrandingResponse:
    """Only the fields present in the request body are touched, so a
    screen that edits one colour cannot blank the rest by omission."""
    principal.require(MANAGE)
    changes = body.model_dump(exclude_unset=True)

    for field in ("primary_color", "secondary_color"):
        colour = changes.get(field)
        if colour is not None:
            branding.assert_readable(colour, against=ON_BRAND, field=field)

    before = _branding(await branding.get_theme(session, tenant_id=principal.tenant_id))
    theme = await branding.upsert_theme(session, tenant_id=principal.tenant_id, changes=changes)
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant",
        entity_id=principal.tenant_id,
        before=before.model_dump(mode="json"),
        after=_branding(theme).model_dump(mode="json"),
    )
    return _branding(theme)


@router.post(
    "/branding/logo",
    response_model=BrandingResponse,
    summary="Upload a logo — virus-scanned like every other upload here",
)
async def upload_logo(
    principal: PrincipalDep,
    session: AuditedSessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> BrandingResponse:
    principal.require(MANAGE)
    data = await file.read()
    if len(data) > LOGO_MAX_BYTES:
        raise AppError("A logo must be under 2 MB.")
    if file.content_type not in LOGO_TYPES:
        raise AppError(
            "A logo must be a PNG, JPEG or WebP image.",
            {"content_type": file.content_type},
        )

    # Fail-closed scanning, REQ-BYPASS-08 — an administrator's upload is
    # trusted no more than a learner's, and an SVG in particular is a
    # script-carrying format.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise AppError(f"That file was rejected by the virus scanner ({result.signature}).")

    # The client filename is not used at all here: the extension comes
    # from the content type we just validated, and the stem is fixed, so
    # there is nothing caller-controlled in the key.
    key = f"tenant-branding/{principal.tenant_id}/logo.{LOGO_TYPES[file.content_type]}"
    await storage.ensure_container(Container.PUBLIC_MARKETING)
    await storage.upload_object(
        Container.PUBLIC_MARKETING, key, data, content_type=file.content_type
    )

    theme = await branding.upsert_theme(
        session, tenant_id=principal.tenant_id, changes={"logo_url": key}
    )
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant",
        entity_id=principal.tenant_id,
        after={"logo_url": key},
    )
    return _branding(theme)


def _domain_row(secret: str, tenant_id: uuid.UUID, domain: TenantDomain) -> DomainRow:
    hostname = str(domain.hostname)
    return DomainRow(
        id=domain.id,
        hostname=hostname,
        is_primary=bool(domain.is_primary),
        verified_at=domain.verified_at,
        tls_status=str(domain.tls_status),
        dns_txt_record=branding.verification_token(
            secret=secret, tenant_id=tenant_id, hostname=hostname
        ),
    )


@router.get(
    "/domains",
    response_model=DomainsResponse,
    summary="Hostnames pointing at this tenant, with the DNS record proving each",
)
async def list_domains(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> DomainsResponse:
    principal.require(MANAGE)
    domains = await branding.list_domains(session, tenant_id=principal.tenant_id)
    return DomainsResponse(
        items=[_domain_row(settings.secret_key, principal.tenant_id, d) for d in domains],
        # False, and honest about it: proving a hostname means resolving
        # its TXT record, which lands with TLS automation in Phase 7.
        # Nothing here marks a domain verified on an admin's say-so —
        # "verified" would then mean only "someone clicked a button".
        verification_available=False,
    )


@router.post(
    "/domains",
    response_model=DomainRow,
    status_code=status.HTTP_201_CREATED,
    summary="Add a hostname — stored unverified until its DNS record is published",
)
async def add_domain(
    body: AddDomainRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    settings: SettingsDep,
) -> DomainRow:
    principal.require(MANAGE)
    domain = await branding.add_domain(
        session, tenant_id=principal.tenant_id, hostname=body.hostname
    )
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant_domain",
        entity_id=domain.id,
        after={"hostname": domain.hostname, "added": True},
    )
    return _domain_row(settings.secret_key, principal.tenant_id, domain)


@router.delete(
    "/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a hostname — never the primary one",
)
async def remove_domain(
    domain_id: uuid.UUID,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    tenant: TenantDep,
) -> None:
    principal.require(MANAGE)
    domain = await branding.remove_domain(
        session, tenant_id=principal.tenant_id, domain_id=domain_id
    )
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant_domain",
        entity_id=domain_id,
        before={"hostname": domain.hostname},
        after={"removed": True},
    )


__all__ = ["router"]
