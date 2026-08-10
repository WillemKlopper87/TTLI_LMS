"""Campaigns, segments, suppression, unsubscribe (02 §10, REQ-CRM-04).

A segment's `criteria` matches only non-PII `leads` attributes (stage,
UTM quintet) — 02 §10/04 §4.4's resolution of encrypted-email-vs-bulk-
marketing: a segment is computed at send time, never a stored list of
addresses. Sending reuses `services/email.py`'s real SMTP path — see
`0019`'s migration docstring for why no separate ESP provider interface
exists here, unlike `services/meeting/`.

Every send checks two independent gates: the contact must hold current
marketing consent (`consent_records`, already built in Phase 2 — a
contact with none or revoked consent is silently excluded, the same
"absent, not present-and-redacted" discipline REQ-TEN-03 established),
and must not be in `suppressions`. A suppressed contact still produces
an `email_sends` row (status `suppressed`) so the campaign's own send
report can show it was correctly withheld — consent-exclusion doesn't,
since that's a precondition on being marketing-reachable at all, not an
outcome of this specific campaign.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.consent import ConsentRecord
from src.models.contact import Contact
from src.models.crm import (
    Campaign,
    EmailEvent,
    EmailSend,
    EmailTemplate,
    Segment,
    Suppression,
)
from src.models.lead import Lead
from src.services import consent as consent_service
from src.services.email import send_email

_UTM_CRITERIA_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


class CampaignError(AppError):
    """A refusal in the marketing flow — an already-sent campaign, or a
    segment/template that doesn't belong to this tenant."""

    code = "CAMPAIGN_ERROR"


async def create_segment(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, criteria: dict[str, str]
) -> Segment:
    segment = Segment(id=uuid7(), tenant_id=tenant_id, name=name, criteria=criteria)
    session.add(segment)
    await session.flush()
    return segment


async def list_segments(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Segment]:
    stmt = select(Segment).where(Segment.tenant_id == tenant_id).order_by(Segment.name)
    return list((await session.execute(stmt)).scalars().all())


def _matches(criteria: dict[str, object], lead: Lead) -> bool:
    if "stage" in criteria and lead.stage != criteria["stage"]:
        return False
    for field in _UTM_CRITERIA_FIELDS:
        if field in criteria and getattr(lead, field) != criteria[field]:
            return False
    return True


async def resolve_segment_contacts(
    session: AsyncSession, *, tenant_id: uuid.UUID, segment_id: uuid.UUID
) -> list[Contact]:
    segment = await session.get(Segment, segment_id)
    if segment is None or segment.tenant_id != tenant_id:
        raise NotFound("No such segment.")
    stmt = (
        select(Lead, Contact)
        .join(Contact, Contact.id == Lead.contact_id)
        .where(Lead.tenant_id == tenant_id)
    )
    rows = (await session.execute(stmt)).all()
    return [contact for lead, contact in rows if _matches(segment.criteria, lead)]


async def create_template(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, subject: str, body_text: str
) -> EmailTemplate:
    template = EmailTemplate(
        id=uuid7(), tenant_id=tenant_id, name=name, subject=subject, body_text=body_text
    )
    session.add(template)
    await session.flush()
    return template


async def list_templates(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[EmailTemplate]:
    stmt = (
        select(EmailTemplate)
        .where(EmailTemplate.tenant_id == tenant_id)
        .order_by(EmailTemplate.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_campaign(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    template_id: uuid.UUID,
    segment_id: uuid.UUID,
) -> Campaign:
    template = await session.get(EmailTemplate, template_id)
    if template is None or template.tenant_id != tenant_id:
        raise NotFound("No such template.")
    segment = await session.get(Segment, segment_id)
    if segment is None or segment.tenant_id != tenant_id:
        raise NotFound("No such segment.")
    campaign = Campaign(
        id=uuid7(), tenant_id=tenant_id, name=name, template_id=template_id, segment_id=segment_id
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def list_campaigns(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Campaign]:
    stmt = (
        select(Campaign).where(Campaign.tenant_id == tenant_id).order_by(Campaign.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _has_marketing_consent(session: AsyncSession, *, contact_id: uuid.UUID) -> bool:
    stmt = (
        select(ConsentRecord.granted)
        .where(ConsentRecord.contact_id == contact_id, ConsentRecord.purpose == "marketing")
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    granted = (await session.execute(stmt)).scalar_one_or_none()
    return bool(granted)


async def _is_suppressed(session: AsyncSession, *, tenant_id: uuid.UUID, contact: Contact) -> bool:
    stmt = select(Suppression.id).where(
        Suppression.tenant_id == tenant_id,
        Suppression.email_blind_index == contact.email_blind_index,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


@dataclass(frozen=True, slots=True)
class SendResult:
    sent: int
    suppressed: int
    excluded_no_consent: int


async def send_campaign(
    session: AsyncSession,
    crypto: CryptoBox,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> SendResult:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise NotFound("No such campaign.")
    if campaign.status != "draft":
        raise CampaignError("This campaign has already been sent.")

    template = await session.get(EmailTemplate, campaign.template_id)
    if template is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such template.")

    contacts = await resolve_segment_contacts(
        session, tenant_id=tenant_id, segment_id=campaign.segment_id
    )

    sent = suppressed = excluded = 0
    for contact in contacts:
        if not await _has_marketing_consent(session, contact_id=contact.id):
            excluded += 1
            continue

        is_suppressed = await _is_suppressed(session, tenant_id=tenant_id, contact=contact)
        email_send = EmailSend(
            id=uuid7(),
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            contact_id=contact.id,
            status="suppressed" if is_suppressed else "queued",
        )
        session.add(email_send)
        await session.flush()

        if is_suppressed:
            suppressed += 1
            continue

        first_name = "there"
        if contact.first_name_encrypted:
            first_name = crypto.decrypt(contact.first_name_encrypted)
        subject = template.subject.replace("{{first_name}}", first_name)
        body = template.body_text.replace("{{first_name}}", first_name)
        body += f"\n\nUnsubscribe: {settings.public_web_url}/unsubscribe/{email_send.id}"
        recipient = crypto.decrypt(contact.email_encrypted)
        await send_email(settings, to=recipient, subject=subject, body=body)

        email_send.status = "sent"
        email_send.sent_at = datetime.now(UTC)
        sent += 1

    campaign.status = "sent"
    campaign.sent_at = datetime.now(UTC)
    await session.flush()
    return SendResult(sent=sent, suppressed=suppressed, excluded_no_consent=excluded)


@dataclass(frozen=True, slots=True)
class CampaignStats:
    campaign: Campaign
    sent: int
    suppressed: int
    bounced: int


async def get_campaign_stats(
    session: AsyncSession, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> CampaignStats:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise NotFound("No such campaign.")
    stmt = select(EmailSend.status).where(EmailSend.campaign_id == campaign_id)
    statuses = (await session.execute(stmt)).scalars().all()
    return CampaignStats(
        campaign=campaign,
        sent=sum(1 for s in statuses if s == "sent"),
        suppressed=sum(1 for s in statuses if s == "suppressed"),
        bounced=sum(1 for s in statuses if s == "bounced"),
    )


async def unsubscribe(session: AsyncSession, *, email_send_id: uuid.UUID) -> None:
    """Public, unauthenticated (a real preference-centre link embedded in
    every sent email) — the only CRM write path that doesn't need a
    principal, by design."""
    email_send = await session.get(EmailSend, email_send_id)
    if email_send is None:
        raise NotFound("No such link.")
    contact = await session.get(Contact, email_send.contact_id)
    if contact is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such contact.")

    existing = await session.execute(
        select(Suppression.id).where(
            Suppression.tenant_id == email_send.tenant_id,
            Suppression.email_blind_index == contact.email_blind_index,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            Suppression(
                id=uuid7(),
                tenant_id=email_send.tenant_id,
                email_blind_index=contact.email_blind_index,
                reason="unsubscribed",
            )
        )
    await consent_service.record(
        session,
        tenant_id=email_send.tenant_id,
        purpose="marketing",
        granted=False,
        source="unsubscribe_link",
        policy_version="v1",
        contact_id=contact.id,
    )
    session.add(
        EmailEvent(
            id=uuid7(),
            tenant_id=email_send.tenant_id,
            email_send_id=email_send.id,
            kind="unsubscribed",
        )
    )
    await session.flush()


async def record_bounce(
    session: AsyncSession, *, tenant_id: uuid.UUID, email_send_id: uuid.UUID, reason: str
) -> None:
    """What a real ESP's bounce webhook would call — structured and
    tested even though no live ESP is wired up to call it yet (02 §10,
    same "real code path, no live external trigger" shape as
    `services/meeting/teams.py`)."""
    email_send = await session.get(EmailSend, email_send_id)
    if email_send is None or email_send.tenant_id != tenant_id:
        raise NotFound("No such email send.")
    contact = await session.get(Contact, email_send.contact_id)
    if contact is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such contact.")

    email_send.status = "bounced"
    existing = await session.execute(
        select(Suppression.id).where(
            Suppression.tenant_id == tenant_id,
            Suppression.email_blind_index == contact.email_blind_index,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            Suppression(
                id=uuid7(),
                tenant_id=tenant_id,
                email_blind_index=contact.email_blind_index,
                reason="bounced",
            )
        )
    session.add(
        EmailEvent(
            id=uuid7(),
            tenant_id=tenant_id,
            email_send_id=email_send.id,
            kind="bounced",
            detail={"reason": reason},
        )
    )
    await session.flush()


__all__ = [
    "CampaignError",
    "CampaignStats",
    "SendResult",
    "create_campaign",
    "create_segment",
    "create_template",
    "get_campaign_stats",
    "list_campaigns",
    "list_segments",
    "list_templates",
    "record_bounce",
    "resolve_segment_contacts",
    "send_campaign",
    "unsubscribe",
]
