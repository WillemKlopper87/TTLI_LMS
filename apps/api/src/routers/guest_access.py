"""Guest account provisioning (03 §4.2, REQ-LEAD-04..07).

Public, rate-limited, always 204 — same enumeration-resistance rule as
POST /leads and the magic-link/password-reset requests: nothing in the
response may reveal whether the email already had an account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from src.core.config import get_settings
from src.core.deps import CryptoDep, SessionDep, SettingsDep, TenantDep
from src.core.errors import AppError
from src.core.net import client_ip
from src.schemas.leads import LeadRequest
from src.services import consent, events, guest_access, identity, rate_limit
from src.services.email import send_email
from src.services.leads import LeadCapture

router = APIRouter(tags=["leads"])

# Mirrors routers/leads.py's POLICY_VERSION — no published privacy policy
# exists yet (Phase 0 is blocked on the customer). Replace once Legal
# delivers one.
POLICY_VERSION = "unpublished-0"


def _client_ip(request: Request) -> str | None:
    return client_ip(request, trust_x_forwarded_for=get_settings().trust_x_forwarded_for)


@router.post(
    "/guest-access",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Provision a time-limited guest account",
    dependencies=[Depends(rate_limit.rate_limited(rate_limit.GUEST_ACCESS))],
)
async def request_guest_access(
    body: LeadRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    tenant: TenantDep,
    settings: SettingsDep,
) -> None:
    if not body.privacy_consent:
        raise AppError("Privacy consent is required to submit this form.")

    granted = await guest_access.grant(
        session,
        crypto,
        tenant_id=tenant.id,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        source=body.source,
        profile={
            "company": body.company,
            "job_title": body.job_title,
            "industry": body.industry,
            "team_size": body.team_size,
            "training_goal": body.training_goal,
            "budget": body.budget,
            "timeline": body.timeline,
        },
        utm={
            "utm_source": body.utm_source,
            "utm_medium": body.utm_medium,
            "utm_campaign": body.utm_campaign,
            "utm_content": body.utm_content,
            "utm_term": body.utm_term,
        },
        guest_days=settings.guest_access_days,
    )

    lead: LeadCapture = granted.lead
    await consent.record(
        session,
        tenant_id=tenant.id,
        contact_id=lead.contact_id,
        purpose="marketing",
        granted=body.marketing_consent,
        source="guest_access_form",
        policy_version=POLICY_VERSION,
        ip=_client_ip(request),
    )

    # REQ-LEAD-06: passwords are never emailed. Always sends a fresh magic
    # link — for a brand-new guest that's their first sign-in; for an
    # existing account (guest or full) it's just a normal sign-in link.
    # None only if the account somehow isn't active (e.g. suspended) —
    # find_by_email() inside create_magic_link() will always see the
    # account grant() just created or reused, so this is a defensive no-op,
    # not the expected path.
    raw = await identity.create_magic_link(
        session, crypto, tenant_id=tenant.id, email=body.email, minutes=settings.magic_link_minutes
    )
    if raw is not None:
        link = f"https://{tenant.hostname}/auth/magic-link?token={raw}"
        await send_email(
            settings,
            to=body.email,
            subject=f"Your {tenant.name} guest access",
            body=(
                f"Use this link to sign in (valid {settings.magic_link_minutes} minutes):\n\n"
                f"{link}\n\nIf you did not request this, ignore this email."
            ),
        )

    await events.record(
        session,
        tenant_id=tenant.id,
        event_name=events.EventName.GUEST_ACCESS_GRANTED,
        user_id=granted.user.id,
        properties={"is_new_guest": granted.is_new_guest, "source": body.source},
        consent_marketing=body.marketing_consent,
    )


__all__ = ["router"]
