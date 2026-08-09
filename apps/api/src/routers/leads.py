"""Lead capture (03 §4.1).

Public, rate-limited, always 204 — same enumeration-resistance rule as
magic-link and password-reset requests, extended here for a different
reason: telling a caller "you're already a lead" is itself a disclosure
about who has expressed interest.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from redis.asyncio import Redis

from src.core.deps import CryptoDep, RedisDep, SessionDep, TenantDep
from src.core.errors import AppError, TooManyAttempts
from src.schemas.leads import LeadRequest
from src.services import consent, events, leads, rate_limit

router = APIRouter(prefix="/leads", tags=["leads"])

# 03 §1.8 has no explicit "leads" row; "Guest signup | 5/hour per IP" is the
# closest documented number for a public funnel-entry endpoint and is reused
# here rather than inventing an unreviewed limit.
LEADS_RATE_LIMIT_PER_IP = 5
LEADS_RATE_LIMIT_WINDOW_SECONDS = 3600

# No published privacy policy exists yet (Phase 0 is blocked on the
# customer, and legal copy is part of that) — this is a placeholder version
# tag so the column is never null, not a real policy identifier. Replace
# once Legal delivers one.
POLICY_VERSION = "unpublished-0"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _enforce_leads_rate_limit(redis: Redis, *, ip: str | None) -> None:
    if ip is None:
        return
    ok = await rate_limit.hit(
        redis,
        key=f"ratelimit:leads:ip:{ip}",
        limit=LEADS_RATE_LIMIT_PER_IP,
        window_seconds=LEADS_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not ok:
        raise TooManyAttempts("Too many attempts. Try again later.")


@router.post(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Capture a lead",
)
async def capture_lead(
    body: LeadRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    tenant: TenantDep,
    redis: RedisDep,
) -> None:
    await _enforce_leads_rate_limit(redis, ip=_client_ip(request))

    if not body.privacy_consent:
        # The one required checkbox — REQ-LEAD-01. Not itself a
        # consent_records purpose (04 §5.1's three purposes are marketing,
        # analytics, ai_processing); this is baseline processing consent
        # needed to accept the submission at all, so it gates acceptance
        # rather than being recorded as a revocable preference.
        raise AppError("Privacy consent is required to submit this form.")

    result = await leads.capture(
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
    )

    await consent.record(
        session,
        tenant_id=tenant.id,
        contact_id=result.contact_id,
        purpose="marketing",
        granted=body.marketing_consent,
        source="leads_form",
        policy_version=POLICY_VERSION,
        ip=_client_ip(request),
    )

    await events.record(
        session,
        tenant_id=tenant.id,
        event_name=events.EventName.LEAD_CAPTURED,
        properties={"is_new_contact": result.is_new_contact, "source": body.source},
        consent_marketing=body.marketing_consent,
    )


__all__ = ["router"]
