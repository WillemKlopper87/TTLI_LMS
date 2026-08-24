"""Admin product-authoring payloads (frontend backlog item 5).

The public storefront shapes (`ProductSummary`/`ProductsPage`) stay in
`schemas/commerce.py` next to the checkout flow that consumes them; these
are the write side, and they carry `is_active`/`course_id`, which the
storefront deliberately never sees.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class ProductCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern="^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    # Optional so a product can be drafted before its course exists, and
    # because 02 §6.1 allows a sellable wrapper with no course behind it.
    course_id: str | None = None
    # Mutually exclusive with course_id — services/catalogue.py::
    # create_product refuses more than one set (P5).
    learning_path_id: str | None = None
    # Mutually exclusive with the two above — a workshop-credit product
    # (P7 phase 4). Sells a *balance*, not the workshop itself; booking
    # stays free/open unless the workshop's own `requires_credit` is set.
    workshop_id: str | None = None


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    course_id: str | None = None
    learning_path_id: str | None = None
    workshop_id: str | None = None
    is_active: bool | None = None


class PriceCreateRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    unit_amount: Decimal = Field(gt=0)
    tax_behaviour: str = Field(default="exclusive", pattern="^(exclusive|inclusive)$")


class AdminPriceRow(BaseModel):
    id: str
    currency: str
    unit_amount: Decimal
    tax_behaviour: str


class AdminProductResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    kind: str
    is_active: bool
    course_id: str | None
    course_title: str | None
    learning_path_id: str | None
    learning_path_title: str | None
    workshop_id: str | None
    workshop_title: str | None
    # Non-null means this product is owned by a subscription plan and must
    # be edited through the plan, not here.
    subscription_plan_id: str | None
    prices: list[AdminPriceRow]


class AdminProductsPage(BaseModel):
    items: list[AdminProductResponse]


class SellableCourseRow(BaseModel):
    """A course this tenant is assigned and could attach to a product."""

    id: str
    title: str
    state: str
    already_sold_as: str | None


class SellableCoursesPage(BaseModel):
    items: list[SellableCourseRow]


__all__ = [
    "AdminPriceRow",
    "AdminProductResponse",
    "AdminProductsPage",
    "PriceCreateRequest",
    "ProductCreateRequest",
    "ProductUpdateRequest",
    "SellableCourseRow",
    "SellableCoursesPage",
]
