"""The public product catalogue (02 §6.1, REQ-STORE-01).

Deliberately thin: a product is sellable, a course is learnable, and the
course/curriculum content model itself is Phase 4 (not built yet). This is
only what the checkout flow built in Phase 3 sprint 1 needs to browse and
buy — active products and their current prices.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.commerce import Price, Product


@dataclass(frozen=True, slots=True)
class PriceRow:
    id: uuid.UUID
    currency: str
    unit_amount: Decimal
    tax_behaviour: str


@dataclass(frozen=True, slots=True)
class ProductRow:
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    kind: str
    prices: list[PriceRow]


async def list_active_products(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[ProductRow]:
    products = (
        (
            await session.execute(
                select(Product)
                .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
                .order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    if not products:
        return []

    product_ids = [p.id for p in products]
    prices = (
        (await session.execute(select(Price).where(Price.product_id.in_(product_ids))))
        .scalars()
        .all()
    )
    prices_by_product: dict[uuid.UUID, list[PriceRow]] = {}
    for price in prices:
        prices_by_product.setdefault(price.product_id, []).append(
            PriceRow(
                id=price.id,
                currency=price.currency,
                unit_amount=price.unit_amount,
                tax_behaviour=price.tax_behaviour,
            )
        )

    return [
        ProductRow(
            id=p.id,
            slug=p.slug,
            name=p.name,
            description=p.description,
            kind=p.kind,
            prices=prices_by_product.get(p.id, []),
        )
        for p in products
    ]


__all__ = ["PriceRow", "ProductRow", "list_active_products"]
