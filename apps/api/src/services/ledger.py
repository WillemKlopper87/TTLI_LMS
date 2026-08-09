"""The append-only financial ledger (02 §6.6). One row per financial event
— `invoice_issued`, `payment_received`, `refund_issued`, `credit_note_issued`,
`write_off`. Not every order-state transition writes one: only these five
represent money or a documented liability actually moving.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.models.commerce import LedgerEntry


class EntryType:
    INVOICE_ISSUED = "invoice_issued"
    PAYMENT_RECEIVED = "payment_received"
    REFUND_ISSUED = "refund_issued"
    CREDIT_NOTE_ISSUED = "credit_note_issued"
    WRITE_OFF = "write_off"


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    entry_type: str,
    amount: Decimal,
    vat_amount: Decimal,
    currency: str,
    tax_code: str | None = None,
    reference: str | None = None,
    created_by: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        LedgerEntry(
            id=uuid7(),
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entry_type=entry_type,
            amount=amount,
            vat_amount=vat_amount,
            currency=currency,
            tax_code=tax_code,
            reference=reference,
            created_by=created_by,
            entry_metadata=metadata or {},
        )
    )
    await session.flush()


__all__ = ["EntryType", "record"]
