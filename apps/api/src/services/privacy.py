"""Data-subject rights (BACKLOG T12, 04_SECURITY_AND_COMPLIANCE.md §5.3).

Personal-data exports are generated only for the authenticated request and returned
directly to the caller. Decrypted export JSON is never persisted in object storage,
Redis, a bearer URL, or another server-side artefact.
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
            "This export covers profile, consent history, course enrolments and certificates, "
            "and orders. It is not yet exhaustive of every category of personal data the "
            "platform holds: workshops, survey responses and CRM contact history remain tracked "
            "as T12 residual scope and must be supplied through the support process until added."
        ),
        "profile": profile,
        "consent": consent,
        "enrolments": enrolments,
        "certificates": certificates,
        "orders": orders,
    }


async def build_export(session: AsyncSession, crypto: CryptoBox, *, user: User) -> bytes:
    """Build an audited JSON export for immediate authenticated download.

    The bytes are returned to the request handler and are never written to a
    storage backend or short-lived cache. This keeps the decrypted copy inside
    the request lifetime only.
    """
    payload = await _export_payload(session, crypto, user=user)
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    await audit.record(
        session,
        tenant_id=user.tenant_id,
        action=AuditAction.PRIVACY_DATA_EXPORTED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    return body


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
    """Anonymise, never delete, preserving financial/accreditation references."""
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


__all__ = ["build_export", "clear_legal_hold", "erase_user", "set_legal_hold"]
