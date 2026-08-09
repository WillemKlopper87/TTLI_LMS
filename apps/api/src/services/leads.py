"""Lead capture (03 §4.1, REQ-LEAD-01…03).

Creates or reuses a contact, then creates or updates that contact's one lead
row per tenant — a second submission from the same person fills in more
progressive-profiling fields (REQ-LEAD-02) rather than creating a second
lead. Consent is written as its own append-only row (services/consent.py),
never inferred from the lead row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.models.contact import Contact
from src.models.lead import Lead

# Fields a submission may progressively fill in. Only non-null incoming
# values overwrite the existing row — a later, sparser submission must not
# erase what an earlier one already captured.
_PROGRESSIVE_FIELDS = (
    "company",
    "job_title",
    "industry",
    "team_size",
    "training_goal",
    "budget",
    "timeline",
)
_UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


@dataclass(frozen=True, slots=True)
class LeadCapture:
    contact_id: uuid.UUID
    lead_id: uuid.UUID
    is_new_contact: bool


async def find_contact_by_email(
    session: AsyncSession, crypto: CryptoBox, email: str
) -> Contact | None:
    index = crypto.blind_index(email)
    stmt = select(Contact).where(Contact.email_blind_index == index)
    return (await session.execute(stmt)).scalar_one_or_none()


async def capture(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    email: str,
    first_name: str | None,
    last_name: str | None,
    source: str | None,
    profile: dict[str, str | None],
    utm: dict[str, str | None],
) -> LeadCapture:
    normalised = email.strip().lower()
    contact = await find_contact_by_email(session, crypto, normalised)
    is_new_contact = contact is None

    if contact is None:
        contact = Contact(
            tenant_id=tenant_id,
            email_encrypted=crypto.encrypt(normalised),
            email_blind_index=crypto.blind_index(normalised),
            email_domain=normalised.split("@", 1)[-1],
            first_name_encrypted=crypto.encrypt(first_name) if first_name else None,
            last_name_encrypted=crypto.encrypt(last_name) if last_name else None,
        )
        session.add(contact)
        await session.flush()
    else:
        if first_name and contact.first_name_encrypted is None:
            contact.first_name_encrypted = crypto.encrypt(first_name)
        if last_name and contact.last_name_encrypted is None:
            contact.last_name_encrypted = crypto.encrypt(last_name)

    lead_stmt = select(Lead).where(Lead.tenant_id == tenant_id, Lead.contact_id == contact.id)
    lead = (await session.execute(lead_stmt)).scalar_one_or_none()

    if lead is None:
        lead = Lead(tenant_id=tenant_id, contact_id=contact.id, source=source)
        session.add(lead)

    for field in _PROGRESSIVE_FIELDS:
        value = profile.get(field)
        if value:
            setattr(lead, field, value)
    for field in _UTM_FIELDS:
        value = utm.get(field)
        if value:
            setattr(lead, field, value)

    await session.flush()
    return LeadCapture(contact_id=contact.id, lead_id=lead.id, is_new_contact=is_new_contact)


__all__ = ["LeadCapture", "capture", "find_contact_by_email"]
