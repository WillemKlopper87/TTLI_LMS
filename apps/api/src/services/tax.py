"""Tax resolution (02 §6.5, REQ-PAY-08).

Tax is data, not code — every rate lives in a `tax_rules` row, matched by
jurisdiction, customer type and product kind, so a rate change or a new
jurisdiction is a data change, not a redeploy. Migration 0009 seeds exactly
one row: South African domestic VAT, 15% at time of writing. Nothing is
seeded for international customers, because 01 §1.4 decision #2 (VAT on
international digital services) is still unsigned — `resolve()` refuses
that case with a clear, specific reason rather than guessing a rate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.models.commerce import TaxRule

# Only the jurisdictions/customer-types that are actually resolvable today.
# 'international' maps to None deliberately — see resolve()'s docstring.
_JURISDICTION_FOR_CUSTOMER_TYPE: dict[str, str | None] = {
    "individual": "ZA",
    "registered_business": "ZA",
    "international": None,
}


class TaxUnresolved(AppError):
    """Raised when no tax treatment can be resolved. Callers must surface
    this as a refusal, never work around it by substituting a guessed rate —
    that is the one thing 02 §6.5 says not to do."""

    code = "TAX_UNRESOLVED"


async def resolve(
    session: AsyncSession, *, tenant_id: uuid.UUID, customer_type: str, product_kind: str
) -> TaxRule:
    jurisdiction = _JURISDICTION_FOR_CUSTOMER_TYPE.get(customer_type)
    if jurisdiction is None:
        raise TaxUnresolved(
            f"Tax treatment for {customer_type!r} customers is not available yet — "
            "01 §1.4 decision #2 (VAT on international digital services) is still "
            "unsigned, so no rate is configured rather than one being guessed."
        )

    now = datetime.now(UTC)
    stmt = (
        select(TaxRule)
        .where(TaxRule.tenant_id == tenant_id)
        .where(TaxRule.jurisdiction == jurisdiction)
        .where((TaxRule.customer_type.is_(None)) | (TaxRule.customer_type == customer_type))
        .where((TaxRule.product_kind.is_(None)) | (TaxRule.product_kind == product_kind))
        .where(TaxRule.valid_from <= now)
        .where((TaxRule.valid_until.is_(None)) | (TaxRule.valid_until > now))
        # A rule naming this exact customer_type/product_kind wins over a
        # wildcard (NULL) one — False sorts before True, so specific matches
        # (is_(None) == False) come first.
        .order_by(TaxRule.customer_type.is_(None), TaxRule.product_kind.is_(None))
        .limit(1)
    )
    rule = (await session.execute(stmt)).scalars().first()
    if rule is None:
        raise TaxUnresolved(
            f"No tax rule is configured for jurisdiction {jurisdiction!r} "
            f"({customer_type!r}, {product_kind!r})."
        )
    return rule


__all__ = ["TaxUnresolved", "resolve"]
