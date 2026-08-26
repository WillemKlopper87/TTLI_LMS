"""Guest account provisioning (03 §4.2, REQ-LEAD-04..07).

Every guest account is unique per lead (REQ-LEAD-04), so provisioning one
always runs the same contact/lead/consent capture as POST /leads first, then
creates — or reuses — a time-limited user tied to that contact's email.
`guest_days` is caller-supplied so the expiry window stays configurable
rather than hardcoded: 01 §1.4 decision #6 (7 vs 14 days) is still unsigned.

REQ-LEAD-05's "sample-only, watermarked" is satisfied structurally, not by
anything in this module: a guest never gets an Enrolment (preview access
is view-only — see services/enrolment.py's has_access_to_video/
can_view_preview, gated on Lesson.access_level == "public" regardless of
who's asking), and routers/media.py::get_playback marks a guest's stream
with a distinct "SAMPLE · GUEST ACCESS" watermark instead of the regular
identity-tracing one. REQ-LEAD-07's conversion (same email, no separate
account) lives in services/orders.py::_fulfil_order, which clears
is_guest/guest_expires_at the moment a guest's order is fulfilled — there
is no "progress" to carry forward because preview never wrote any.

The hourly expiry-downgrade sweep (02 §12.4's "Guest expiry sweep") is
still out of scope: expiry is enforced at the two points that actually
gate access — magic-link consumption and refresh rotation
(services/identity.py, services/tokens.py) — rather than by a background
job that doesn't exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.models.user import User
from src.services import identity
from src.services.leads import LeadCapture, capture


@dataclass(frozen=True, slots=True)
class GuestAccess:
    lead: LeadCapture
    user: User
    is_new_guest: bool


async def grant(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: UUID,
    email: str,
    first_name: str | None,
    last_name: str | None,
    source: str | None,
    profile: dict[str, str | None],
    utm: dict[str, str | None],
    guest_days: int,
) -> GuestAccess:
    lead = await capture(
        session,
        crypto,
        tenant_id=tenant_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        source=source,
        profile=profile,
        utm=utm,
    )

    existing = await identity.find_by_email(session, crypto, email)

    if existing is not None and not existing.is_guest:
        # Already a full account (or converted from one) — never downgrade
        # or duplicate it. The caller still sends a magic link, so this
        # person just signs into the account they already have.
        return GuestAccess(lead=lead, user=existing, is_new_guest=False)

    if existing is not None and existing.is_guest:
        # REQ-LEAD-04: unique per lead. A repeat request refreshes the
        # window rather than minting a second guest account.
        existing.guest_expires_at = datetime.now(UTC) + timedelta(days=guest_days)
        await session.flush()
        return GuestAccess(lead=lead, user=existing, is_new_guest=False)

    full_name = " ".join(part for part in (first_name, last_name) if part) or None
    user = await identity.create_user(
        session,
        crypto,
        tenant_id=tenant_id,
        email=email,
        full_name=full_name,
        is_guest=True,
        guest_days=guest_days,
    )
    return GuestAccess(lead=lead, user=user, is_new_guest=True)


__all__ = ["GuestAccess", "grant"]
