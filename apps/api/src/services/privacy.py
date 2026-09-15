"""Data-subject rights (BACKLOG T12, 04_SECURITY_AND_COMPLIANCE.md §5.3).

Four of the five rows in that section's table get their implementation
here; the fifth (objection to marketing) already exists as `suppressions`
and `services.campaigns.unsubscribe` and is untouched by this module:

- Access / Portability: `build_export` assembles a JSON document,
  uploaded to `GENERATED_DOCUMENTS`, delivered the same way
  `credentials.py` already signs a URL for a certificate PDF.
- Correction: self-service profile editing, wherever it lands, is
  already audited by convention — nothing new to add here.
- Deletion: `erase_user` anonymises, never `DELETE`s. The row survives
  so anything financial (orders, invoices) that references it stays
  intact; only identity columns are tombstoned.
- Legal hold: `set_legal_hold` / `clear_legal_hold` are the mechanism
  §5.3's own gap note in the security doc ("no mechanism is specified
  for suspending deletion during a dispute") says is needed before the
  first enterprise contract.

Erasure reuses `services.tenant_users.set_status`'s exact session-
termination mechanism (suspend, not a new status value) rather than
inventing a third account state the rest of the codebase would need to
learn about for one event.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError
from src.models.audit import AuditAction
from src.models.commerce import Order
from src.models.consent import ConsentRecord
from src.models.course import Course
from src.models.credential import Certificate
from src.models.learning import Enrolment
from src.models.user import User
from src.services import audit, tokens
from src.services.storage.base import Container, StorageService

EXPORT_EXPIRES_IN_SECONDS = 300


async def _export_payload(
    session: AsyncSession, crypto: CryptoBox, *, user: User
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "user_id": str(user.id),
        "email": crypto.decrypt(user.email_encrypted),
        "full_name": crypto.decrypt(user.full_name_encrypted) if user.full_name_encrypted else None,
        "phone": crypto.decrypt(user.phone_encrypted) if user.phone_encrypted else None,
        "status": user.status,
        "is_guest": user.is_guest,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }

    consent_rows = (
        await session.execute(
            select(ConsentRecord)
            .where(ConsentRecord.tenant_id == user.tenant_id, ConsentRecord.user_id == user.id)
            .order_by(ConsentRecord.created_at)
        )
    ).scalars()
    consent = [
        {
            "purpose": c.purpose,
            "granted": c.granted,
            "source": c.source,
            "policy_version": c.policy_version,
            "recorded_at": c.created_at.isoformat(),
        }
        for c in consent_rows
    ]

    enrolment_rows = (
        await session.execute(
            select(Enrolment, Course.title)
            .join(Course, Course.id == Enrolment.course_id)
            .where(Enrolment.tenant_id == user.tenant_id, Enrolment.user_id == user.id)
            .order_by(Enrolment.created_at)
        )
    ).all()
    enrolments = [
        {
            "course": title,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
        }
        for e, title in enrolment_rows
    ]

    enrolment_ids = [e.id for e, _ in enrolment_rows]
    certificates: list[dict[str, Any]] = []
    if enrolment_ids:
        cert_rows = (
            await session.execute(
                select(Certificate).where(
                    Certificate.tenant_id == user.tenant_id,
                    Certificate.enrolment_id.in_(enrolment_ids),
                )
            )
        ).scalars()
        certificates = [
            {
                "certificate_number": c.certificate_number,
                "issued_at": c.issued_at.isoformat(),
                "status": c.status,
                "title": c.snapshot.get("title"),
            }
            for c in cert_rows
        ]

    order_rows = (
        await session.execute(
            select(Order)
            .where(Order.tenant_id == user.tenant_id, Order.user_id == user.id)
            .order_by(Order.created_at)
        )
    ).scalars()
    orders = [
        {
            "status": o.status,
            "currency": o.currency,
            "grand_total": str(o.grand_total),
            "created_at": o.created_at.isoformat(),
        }
        for o in order_rows
    ]

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "note": (
            "This export covers profile, consent history, course "
            "enrolments and certificates, and orders. It is not yet "
            "exhaustive of every category of personal data the platform "
            "holds (workshops, survey responses and CRM contact history "
            "are not included) — request an extension from support if "
            "you need one of those."
        ),
        "profile": profile,
        "consent": consent,
        "enrolments": enrolments,
        "certificates": certificates,
        "orders": orders,
    }


async def build_export(
    session: AsyncSession,
    crypto: CryptoBox,
    storage: StorageService,
    *,
    user: User,
) -> str:
    """Assemble the export and return a short-lived signed download URL.

    Synchronous, matching how certificate PDFs are generated inline
    (services/enrolment.py) rather than via the worker — this is a JSONB
    read-and-serialise over a handful of tables, not a transcode.
    """
    payload = await _export_payload(session, crypto, user=user)
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    key = f"privacy-exports/{user.tenant_id}/{user.id}/{uuid.uuid4()}.json"
    await storage.upload_object(
        Container.GENERATED_DOCUMENTS, key, body, content_type="application/json"
    )
    url = await storage.generate_signed_url(
        Container.GENERATED_DOCUMENTS, key, expires_in=EXPORT_EXPIRES_IN_SECONDS
    )
    await audit.record(
        session,
        tenant_id=user.tenant_id,
        action=AuditAction.PRIVACY_DATA_EXPORTED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    return url


_TOMBSTONE_NAME = "Erased user"


async def erase_user(
    session: AsyncSession,
    crypto: CryptoBox,
    redis: Redis,
    *,
    user: User,
    actor_user_id: uuid.UUID,
    access_token_ttl_seconds: int,
) -> None:
    """Anonymise, never delete. `user` survives so every FK pointing at it
    (orders, invoices, enrolments, audit history) stays intact — exactly
    04_SECURITY_AND_COMPLIANCE.md §5.3's "financial retention outranks
    erasure" line, which this makes true by construction rather than by
    convention: there is no code path that deletes the row at all.
    """
    if user.legal_hold:
        raise AppError(
            "This account is under legal hold and cannot be erased.",
            {"legal_hold_reason": user.legal_hold_reason},
        )
    if user.erased_at is not None:
        raise AppError("This account has already been erased.")

    tombstone_email = f"erased-{user.id}@erased.invalid"
    user.email_encrypted = crypto.encrypt(tombstone_email)
    user.email_blind_index = crypto.blind_index(tombstone_email)
    user.email_domain = "erased.invalid"
    user.full_name_encrypted = crypto.encrypt(_TOMBSTONE_NAME)
    user.phone_encrypted = None
    user.mfa_secret_encrypted = None
    user.password_hash = None
    user.status = "suspended"
    user.erased_at = datetime.now(UTC)
    await session.flush()

    # Same session-termination mechanism services.tenant_users.set_status
    # uses on suspension (fable5.1_review.md H-11) — an erased identity
    # must not keep a live refresh token or a still-valid access token.
    await tokens.revoke_all_for_user(session, user_id=user.id)
    await tokens.revoke_access_tokens_for_user(
        redis, user_id=user.id, ttl_seconds=access_token_ttl_seconds
    )

    await audit.record(
        session,
        tenant_id=user.tenant_id,
        action=AuditAction.PRIVACY_USER_ERASED,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
    )


async def set_legal_hold(
    session: AsyncSession, *, user: User, reason: str, actor_user_id: uuid.UUID
) -> None:
    user.legal_hold = True
    user.legal_hold_reason = reason
    user.legal_hold_set_at = datetime.now(UTC)
    user.legal_hold_set_by = actor_user_id
    await session.flush()
    await audit.record(
        session,
        tenant_id=user.tenant_id,
        action=AuditAction.PRIVACY_LEGAL_HOLD_SET,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
        after={"reason": reason},
    )


async def clear_legal_hold(session: AsyncSession, *, user: User, actor_user_id: uuid.UUID) -> None:
    if not user.legal_hold:
        raise AppError("This account is not under legal hold.")
    before_reason = user.legal_hold_reason
    user.legal_hold = False
    user.legal_hold_reason = None
    user.legal_hold_set_at = None
    user.legal_hold_set_by = None
    await session.flush()
    await audit.record(
        session,
        tenant_id=user.tenant_id,
        action=AuditAction.PRIVACY_LEGAL_HOLD_CLEARED,
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=user.id,
        before={"reason": before_reason},
    )


__all__ = [
    "EXPORT_EXPIRES_IN_SECONDS",
    "build_export",
    "clear_legal_hold",
    "erase_user",
    "set_legal_hold",
]
